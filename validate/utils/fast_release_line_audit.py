#!/usr/bin/env python3
"""Fast line-level audit for very large release JSONL files.

This avoids full JSON parsing and is meant for first-pass full-dataset ratios on
huge JSONL releases. It scans each physical line for instance_id, task, language
signals, sensitive keywords, challenge/parked pages, and remote URLs.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import re
from pathlib import Path


ADULT = [
    "adult", "porn", "porno", "sex", "xxx", "escort", "escorts", "dating",
    "casino", "gambling", "betting", "call-girls", "callgirls", "webcam",
    "nude", "erotic", "hookup", "bdsm",
]
CHALLENGE = ["captcha", "cloudflare", "access denied", "checking your browser", "are you human", "security check"]
PLACEHOLDER = ["placeholder", "lorem ipsum", "domain for sale", "parked domain", "under construction", "coming soon"]

INSTANCE_RE = re.compile(rb'"instance_id"\s*:\s*"((?:\\"|[^"])*)"')
TASK_RE = re.compile(rb'"task"\s*:\s*"((?:\\"|[^"])*)"')


def unescape_jsonish(raw: bytes) -> str:
    try:
        return json.loads(b'"' + raw + b'"')
    except Exception:
        return raw.decode("utf-8", "ignore")


def language_flag(text: str) -> str | None:
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < 30:
        return "too_little_text"
    cjk = sum("\u4e00" <= ch <= "\u9fff" for ch in letters)
    ascii_letters = sum("a" <= ch.lower() <= "z" for ch in letters)
    latin_ext = sum("\u00c0" <= ch <= "\u024f" for ch in letters)
    other = len(letters) - cjk - ascii_letters - latin_ext
    if (cjk + ascii_letters) / len(letters) < 0.55:
        return "likely_non_zh_en"
    if latin_ext / len(letters) > 0.25:
        return "likely_non_english_latin"
    if other / len(letters) > 0.25:
        return "likely_other_script"
    return None


def hits(text: str, words: list[str]) -> list[str]:
    low = text.lower()
    return [w for w in words if w in low]


def scan_file(path: Path, sample_chars: int) -> dict:
    total = 0
    issues = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    task_counter = Counter()
    with path.open("rb") as f:
        for raw in f:
            if not raw.strip():
                continue
            total += 1
            inst_m = INSTANCE_RE.search(raw)
            task_m = TASK_RE.search(raw)
            instance_id = unescape_jsonish(inst_m.group(1)) if inst_m else f"{path.name}:{total}"
            task = unescape_jsonish(task_m.group(1)) if task_m else path.stem
            task_counter[task] += 1
            prefix = raw[:sample_chars].decode("utf-8", "ignore")
            full_low = raw.lower()

            line_issues = []
            lang = language_flag(prefix)
            if lang:
                line_issues.append(lang)
            adult_hits = hits((instance_id + "\n" + prefix).lower(), ADULT)
            if adult_hits:
                line_issues.append("adult_or_sensitive:" + ",".join(adult_hits[:5]))
            if any(w.encode() in full_low for w in CHALLENGE):
                line_issues.append("challenge_or_captcha")
            if any(w.encode() in full_low for w in PLACEHOLDER):
                line_issues.append("placeholder_or_parked")
            if b"http://" in raw or b"https://" in raw:
                line_issues.append("remote_url_present")
            if b'"input_files"' not in raw and ("edit" in task or "repair" in task):
                line_issues.append("patch_uncheckable_missing_input_files")
            if b'"dst_screenshot"' not in raw and task == "image-repair":
                line_issues.append("missing_dst_screenshot")

            for issue in sorted(set(line_issues)):
                issues[issue] += 1
                if len(examples[issue]) < 10:
                    examples[issue].append(instance_id)

    return {
        "file": str(path),
        "total": total,
        "tasks": dict(task_counter),
        "issues": dict(issues),
        "examples": dict(examples),
    }


def render_md(results: list[dict]) -> str:
    lines = ["# Fast Release Line Audit", ""]
    for result in results:
        total = result["total"]
        lines.append(f"## `{result['file']}`")
        lines.append("")
        lines.append(f"- total: {total}")
        lines.append(f"- tasks: `{result['tasks']}`")
        lines.append("")
        lines.append("| issue | count | ratio | examples |")
        lines.append("|---|---:|---:|---|")
        for issue, count in Counter(result["issues"]).most_common():
            ratio = count / total if total else 0
            examples = ", ".join(result["examples"].get(issue, [])[:5])
            lines.append(f"| `{issue}` | {count} | {ratio:.2%} | `{examples}` |")
        lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- This is a fast line-level audit. It is conservative and may over-count because it scans code, metadata, and instructions together.")
    lines.append("- Patch uniqueness requires full JSON parsing plus code fields. Release text-edit/text-repair files do not include `input_files`, so they are uncheckable in this release format.")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--sample-chars", type=int, default=100_000)
    args = parser.parse_args()

    files = []
    for path in args.paths:
        if path.is_dir():
            files.extend(sorted(path.glob("*.jsonl")))
        else:
            files.append(path)
    results = [scan_file(path, args.sample_chars) for path in files]
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "fast_line_audit.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.out_dir / "fast_line_audit.md").write_text(render_md(results), encoding="utf-8")
    print(json.dumps({"files": len(files), "out_dir": str(args.out_dir)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
