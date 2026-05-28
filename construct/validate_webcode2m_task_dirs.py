#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
from typing import Any


TASK_DIRS = {
    "text-generation": "text-generation",
    "image-generation": "image-generation",
    "video-generation": "video-generation",
    "text-editing": "text-editing",
    "image-editing": "image-editing",
    "text-repair": "text-repair",
    "image-repair": "image-repair",
}
REMOTE_RE = re.compile(r"https?://|(?<![A-Za-z0-9+/=])//[A-Za-z0-9][A-Za-z0-9.-]*(?:[/:]|$)", re.I)
REMOTE_LOAD_RE = re.compile(
    r"(?:url\(\s*['\"]?https?://|@import\s+['\"]https?://|"
    r"\b(?:src|srcset|poster|action)\s*=\s*['\"]https?://)",
    re.I,
)
SVG_NAMESPACE_URLS = {
    "http://www.w3.org/2000/svg",
    "http://www.w3.org/1999/xlink",
    "http://purl.org/dc/elements/1.1/",
    "http://creativecommons.org/ns#",
    "http://www.inkscape.org/namespaces/inkscape",
    "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd",
    "http://www.serif.com/",
}
PROVENANCE_FILES = {"metadata.json", "original_webcode2m_screenshot.png"}


def iter_info_files(task_root: Path) -> list[Path]:
    return sorted(task_root.rglob("info.json")) if task_root.exists() else []


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate(root: Path, expected_per_task: int = 0) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    task_counts: Counter[str] = Counter()

    for task, dirname in TASK_DIRS.items():
        task_root = root / dirname
        infos = iter_info_files(task_root)
        task_counts[task] = len(infos)
        if expected_per_task and len(infos) != expected_per_task:
            errors.append(f"{task}: expected {expected_per_task} info.json files, found {len(infos)}")

        for info_path in infos:
            try:
                info = load_json(info_path)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{info_path}: invalid json: {type(exc).__name__}: {exc}")
                continue
            if info.get("task") != task:
                errors.append(f"{info_path}: task field is {info.get('task')!r}, expected {task!r}")
            if task == "text-generation":
                instruction = str(info.get("instruction") or "")
                if len(instruction) < 800:
                    errors.append(f"{info_path}: PRD instruction too short")
                banned_patterns = (
                    r"\bscreenshots?\b",
                    r"\breverse construction\b",
                    r"\bsource website\b",
                    r"\bhidden implementation\b",
                )
                lowered = instruction.lower()
                if any(re.search(pattern, lowered) for pattern in banned_patterns):
                    errors.append(f"{info_path}: PRD leaks construction/source wording")
                if not info.get("input_screenshots"):
                    errors.append(f"{info_path}: text-generation missing PRD source screenshots")
            if task == "image-generation" and not info.get("input_screenshots"):
                errors.append(f"{info_path}: image-generation missing input_screenshots")
            if task == "video-generation" and not info.get("input_videos"):
                errors.append(f"{info_path}: video-generation missing input_videos")
            if task.endswith("editing"):
                if not info.get("src_code") or not info.get("dst_code"):
                    errors.append(f"{info_path}: editing pair missing src_code or dst_code")
                if not info.get("label_modified_files"):
                    errors.append(f"{info_path}: editing pair missing label_modified_files")
            if task.endswith("repair"):
                if not info.get("src_code") or not info.get("dst_code"):
                    errors.append(f"{info_path}: repair pair missing src_code or dst_code")
                patches = info.get("label_modified_files") or []
                if not patches:
                    errors.append(f"{info_path}: repair pair missing reverse label_modified_files")
            if task.startswith("image-"):
                if not info.get("src_screenshot") and task in {"image-editing", "image-repair"}:
                    errors.append(f"{info_path}: visual edit/repair missing src_screenshot")
                if not info.get("dst_screenshot") and task in {"image-editing", "image-repair"}:
                    errors.append(f"{info_path}: visual edit/repair missing dst_screenshot")

    html_hits = []
    provenance_hits = []
    small_videos = []
    for path in root.rglob("*"):
        if path.name in PROVENANCE_FILES:
            provenance_hits.append(str(path))
        if path.suffix.lower() in {".html", ".htm", ".css", ".js", ".svg"}:
            text = path.read_text(encoding="utf-8", errors="ignore")
            without_namespaces = text
            for url in SVG_NAMESPACE_URLS:
                without_namespaces = without_namespaces.replace(url, "")
            if REMOTE_LOAD_RE.search(without_namespaces):
                html_hits.append(str(path))
        if path.suffix.lower() == ".webm" and path.stat().st_size < 1024:
            small_videos.append(str(path))

    if provenance_hits:
        errors.append(f"provenance files leaked: {len(provenance_hits)}")
    if html_hits:
        errors.append(f"remote URL remnants found in render code: {len(html_hits)}")
    if small_videos:
        errors.append(f"video files too small: {len(small_videos)}")

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "task_counts": dict(task_counts),
        "info_json_count": sum(task_counts.values()),
        "remote_hit_count": len(html_hits),
        "provenance_hit_count": len(provenance_hits),
        "small_video_count": len(small_videos),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--expected-per-task", type=int, default=0)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()

    report = validate(args.root, args.expected_per_task)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
