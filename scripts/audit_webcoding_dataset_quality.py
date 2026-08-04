#!/usr/bin/env python3
"""Audit WebCoding JSONL datasets for quality risks.

The script is read-only. It scans one or more JSONL files, computes per-task
issue rates, and writes JSON + Markdown reports. It is intentionally heuristic:
the goal is to quickly surface suspicious samples before expensive manual review.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import json
import math
import re
from pathlib import Path
from typing import Any


ADULT_KEYWORDS = {
    "adult", "porn", "porno", "sex", "xxx", "escort", "escorts", "dating",
    "casino", "gambling", "bet", "bets", "betting", "call-girls", "callgirls",
    "cam", "cams", "webcam", "nude", "nudes", "erotic", "hookup", "shemale",
}

CHALLENGE_KEYWORDS = {
    "cloudflare", "captcha", "access denied", "are you human", "checking your browser",
    "enable javascript", "security check", "verify you are", "just a moment",
}

PLACEHOLDER_KEYWORDS = {
    "lorem ipsum", "placeholder", "coming soon", "under construction",
    "domain for sale", "parked domain", "this domain", "buy this domain",
}

REMOTE_URL_RE = re.compile(r"https?://|//[A-Za-z0-9.-]+")
DOMAINISH_RE = re.compile(r"([A-Za-z0-9-]+\.)+[A-Za-z]{2,}")


def read_jsonl(path: Path, limit: int = 0):
    with path.open("rb") as f:
        for index, raw in enumerate(f, start=1):
            if limit and index > limit:
                break
            if not raw.strip():
                continue
            try:
                yield index, json.loads(raw)
            except Exception as exc:  # noqa: BLE001
                yield index, {"__parse_error__": f"{type(exc).__name__}: {exc}"}


def compact_text(value: Any, max_chars: int = 50_000) -> str:
    chunks: list[str] = []
    total = 0

    def walk(item: Any) -> None:
        nonlocal total
        if total >= max_chars:
            return
        if isinstance(item, str):
            take = item[: max_chars - total]
            chunks.append(take)
            total += len(take)
        elif isinstance(item, list):
            for child in item:
                walk(child)
        elif isinstance(item, dict):
            for child in item.values():
                walk(child)

    walk(value)
    return "\n".join(chunks)[:max_chars]


def code_files(record: dict[str, Any], key: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for item in record.get(key, []) or []:
        if isinstance(item, dict) and isinstance(item.get("path"), str) and isinstance(item.get("code"), str):
            files[item["path"]] = item["code"]
    return files


def detect_task(record: dict[str, Any], path: Path) -> str:
    task = record.get("task")
    if isinstance(task, str) and task:
        return task
    name = path.name.lower()
    for candidate in [
        "text-generation", "image-generation", "video-generation",
        "text-editing", "image-editing", "text-repair", "image-repair",
        "text-generate", "image-generate", "text-edit", "image-edit",
        "text-repair", "image-repair",
    ]:
        if candidate in name:
            return candidate
    return "unknown"


def sample_id(record: dict[str, Any], path: Path, index: int) -> str:
    for key in ["instance_id", "id", "hash"]:
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return f"{path.name}:{index}"


def language_issue(text: str) -> str | None:
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 20:
        return "too_little_text"
    cjk = sum("\u4e00" <= ch <= "\u9fff" for ch in letters)
    ascii_letters = sum(("a" <= ch.lower() <= "z") for ch in letters)
    latin_ext = sum(("\u00c0" <= ch <= "\u024f") for ch in letters)
    other_alpha = len(letters) - cjk - ascii_letters - latin_ext
    allowed = cjk + ascii_letters
    if allowed / max(1, len(letters)) < 0.55:
        return "likely_non_zh_en"
    if latin_ext / max(1, len(letters)) > 0.25:
        return "likely_non_english_latin"
    if other_alpha / max(1, len(letters)) > 0.25:
        return "likely_other_script"
    return None


def keyword_hits(text: str, keywords: set[str]) -> list[str]:
    lowered = text.lower()
    hits = []
    for kw in sorted(keywords):
        if kw in lowered:
            hits.append(kw)
    return hits


def domain_risk(record: dict[str, Any], text: str) -> list[str]:
    haystack = " ".join([
        str(record.get("instance_id", "")),
        str(record.get("url", "")),
        str(record.get("source_url", "")),
        text[:20_000],
    ]).lower()
    return keyword_hits(haystack, ADULT_KEYWORDS)


def patch_issues(record: dict[str, Any], task: str) -> list[str]:
    if "edit" not in task and "repair" not in task:
        return []
    patches = record.get("patches", record.get("response", []))
    if not patches:
        return ["missing_patches"]
    if not isinstance(patches, list):
        return ["patches_not_list"]

    before = code_files(record, "input_files") or code_files(record, "src_code")
    after = code_files(record, "output_files") or code_files(record, "dst_code")
    issues: list[str] = []
    if not before:
        return ["patch_uncheckable_missing_input_code"]
    for idx, patch in enumerate(patches):
        if not isinstance(patch, dict):
            issues.append(f"patch_{idx}_not_dict")
            continue
        path = patch.get("path")
        search = patch.get("search")
        replace = patch.get("replace")
        if not isinstance(path, str) or not isinstance(search, str) or not isinstance(replace, str):
            issues.append(f"patch_{idx}_bad_types")
            continue
        if path not in before:
            issues.append(f"patch_{idx}_path_missing_input")
            continue
        count = before[path].count(search)
        if count == 0:
            issues.append(f"patch_{idx}_search_not_found")
        elif count > 1:
            issues.append(f"patch_{idx}_search_ambiguous_{count}")
        if not after:
            issues.append(f"patch_{idx}_replace_uncheckable_missing_output_code")
        elif path in after and replace not in after[path]:
            issues.append(f"patch_{idx}_replace_not_in_output")
    return issues


def schema_issues(record: dict[str, Any]) -> list[str]:
    issues = []
    task = record.get("task")
    if not isinstance(record.get("instance_id"), str):
        issues.append("missing_instance_id")
    if not isinstance(task, str):
        issues.append("missing_task")
    if task in {"image-generation", "image-editing", "image-repair"} and not record.get("input_images"):
        issues.append("missing_input_images")
    if task == "image-repair" and not record.get("dst_screenshot"):
        issues.append("missing_dst_screenshot")
    if task in {"text-editing", "image-editing", "text-repair", "image-repair"}:
        if not record.get("input_files") and not record.get("src_code"):
            issues.append("missing_input_files")
        if not record.get("output_files") and not record.get("dst_code"):
            issues.append("missing_output_files")
    return issues


def remote_resource_issue(text: str) -> str | None:
    if REMOTE_URL_RE.search(text):
        return "remote_url_present"
    return None


def possible_domain(record: dict[str, Any]) -> str:
    value = str(record.get("instance_id", ""))
    match = DOMAINISH_RE.search(value.replace("__", "/").replace("_", "."))
    return match.group(0).lower() if match else ""


def image_diff_score(root: Path, record: dict[str, Any]) -> float | None:
    try:
        from PIL import Image, ImageChops, ImageStat
    except Exception:
        return None

    src_list = record.get("src_screenshot") or record.get("input_images") or []
    dst_list = record.get("dst_screenshot") or []
    if not src_list or not dst_list:
        return None
    src = root / src_list[0]
    dst = root / dst_list[0]
    if not src.exists() or not dst.exists():
        return None
    try:
        with Image.open(src) as a_raw, Image.open(dst) as b_raw:
            a = a_raw.convert("RGB").resize((256, 256))
            b = b_raw.convert("RGB").resize((256, 256))
            diff = ImageChops.difference(a, b)
            stat = ImageStat.Stat(diff)
            rms = math.sqrt(sum(v * v for v in stat.mean) / len(stat.mean)) / 255.0
            return float(rms)
    except Exception:
        return None


@dataclass
class TaskStats:
    total: int = 0
    issue_counts: Counter[str] = field(default_factory=Counter)
    examples: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))

    def add(self, issues: list[str], sid: str) -> None:
        self.total += 1
        for issue in sorted(set(issues)):
            self.issue_counts[issue] += 1
            if len(self.examples[issue]) < 10:
                self.examples[issue].append(sid)


def add_issue(issues: list[str], issue: str | None) -> None:
    if issue:
        issues.append(issue)


def audit_file(
    path: Path,
    root: Path,
    limit: int,
    text_max_chars: int,
    skip_image_diff: bool,
    stats: dict[str, TaskStats],
    file_counts: Counter[str],
) -> None:
    for index, record in read_jsonl(path, limit):
        task = detect_task(record, path)
        sid = sample_id(record, path, index)
        issues: list[str] = []
        if "__parse_error__" in record:
            issues.append("json_parse_error")
            stats[task].add(issues, sid)
            file_counts[str(path)] += 1
            continue

        text = compact_text(record, text_max_chars)
        issues.extend(schema_issues(record))
        add_issue(issues, language_issue(text))
        if hits := domain_risk(record, text):
            issues.append("adult_or_sensitive_keyword:" + ",".join(hits[:5]))
        if hits := keyword_hits(text, CHALLENGE_KEYWORDS):
            issues.append("challenge_or_captcha:" + ",".join(hits[:5]))
        if hits := keyword_hits(text, PLACEHOLDER_KEYWORDS):
            issues.append("placeholder_or_parked:" + ",".join(hits[:5]))
        add_issue(issues, remote_resource_issue(text))
        patch_flags = patch_issues(record, task)
        issues.extend(patch_flags)

        if task == "image-repair" and not skip_image_diff:
            score = image_diff_score(root, record)
            if score is None:
                issues.append("image_repair_diff_unavailable")
            elif score < 0.015:
                issues.append("image_repair_very_low_visual_diff")
            elif score < 0.035:
                issues.append("image_repair_low_visual_diff")

        domain = possible_domain(record)
        if domain and any(token in domain for token in ADULT_KEYWORDS):
            issues.append("risky_domain_from_instance_id")

        stats[task].add(issues, sid)
        file_counts[str(path)] += 1


def render_markdown(stats: dict[str, TaskStats], file_counts: Counter[str], source_paths: list[Path]) -> str:
    lines = [
        "# WebCoding 数据质量审计报告",
        "",
        "## 输入",
        "",
    ]
    for path in source_paths:
        lines.append(f"- `{path}`")
    lines.extend(["", "## 文件计数", ""])
    for path, count in file_counts.most_common():
        lines.append(f"- `{path}`: {count}")
    lines.extend(["", "## 按任务统计", ""])
    for task in sorted(stats):
        st = stats[task]
        lines.append(f"### {task}")
        lines.append("")
        lines.append(f"- total: {st.total}")
        if not st.issue_counts:
            lines.append("- 未发现启发式问题")
            lines.append("")
            continue
        lines.append("")
        lines.append("| issue | count | ratio | examples |")
        lines.append("|---|---:|---:|---|")
        for issue, count in st.issue_counts.most_common():
            ratio = count / st.total if st.total else 0
            examples = ", ".join(st.examples.get(issue, [])[:5])
            lines.append(f"| `{issue}` | {count} | {ratio:.2%} | `{examples}` |")
        lines.append("")
    lines.extend([
        "## 解读",
        "",
        "- `likely_non_zh_en` / `likely_non_english_latin` / `likely_other_script`: 语言启发式，不替代人工或 fastText/langid，但适合作为第一轮剔除候选。",
        "- `adult_or_sensitive_keyword:*` 和 `risky_domain_from_instance_id`: 域名、路径或页面文本命中成人/博彩/约会等风险词。",
        "- `patch_*_search_not_found` / `patch_*_search_ambiguous_*`: patch 不能在输入代码中唯一匹配，edit/repair 监督不可靠。",
        "- `image_repair_low_visual_diff`: repair 前后截图差异过小，可能是视觉无关 bug，也可能是不适合作为 image-repair 的样本。",
        "- `remote_url_present`: 训练样本仍含远程 URL，需进一步区分允许的图片替代 URL与应本地化的资源。",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path, help="JSONL files or directories")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--limit-per-file", type=int, default=0)
    parser.add_argument("--text-max-chars", type=int, default=50_000)
    parser.add_argument("--skip-image-diff", action="store_true")
    parser.add_argument("--dataset-root", type=Path, default=None, help="Root used to resolve image paths")
    args = parser.parse_args()

    jsonl_paths: list[Path] = []
    for path in args.paths:
        if path.is_dir():
            jsonl_paths.extend(sorted(path.rglob("*.jsonl")))
        elif path.suffix == ".jsonl":
            jsonl_paths.append(path)
    if not jsonl_paths:
        raise SystemExit("no JSONL files found")

    root = args.dataset_root or (jsonl_paths[0].parent if len(jsonl_paths) == 1 else Path.cwd())
    stats: dict[str, TaskStats] = defaultdict(TaskStats)
    file_counts: Counter[str] = Counter()
    for path in jsonl_paths:
        audit_file(path, root, args.limit_per_file, args.text_max_chars, args.skip_image_diff, stats, file_counts)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    serializable = {
        task: {
            "total": st.total,
            "issue_counts": dict(st.issue_counts),
            "examples": dict(st.examples),
        }
        for task, st in sorted(stats.items())
    }
    (args.out_dir / "quality_audit.json").write_text(
        json.dumps({"files": dict(file_counts), "tasks": serializable}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.out_dir / "quality_audit.md").write_text(
        render_markdown(stats, file_counts, jsonl_paths),
        encoding="utf-8",
    )
    print(json.dumps({"out_dir": str(args.out_dir), "files": len(jsonl_paths)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
