#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def resolve_projects_dir(input_dir: Path) -> Path:
    projects = input_dir / "projects"
    return projects if projects.exists() else input_dir


def run_step(args: list[str]) -> None:
    print("+ " + " ".join(args), flush=True)
    subprocess.run(args, cwd=REPO_ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Thin WebCode2M dataset driver. Each task type stays in its own constructor module."
    )
    parser.add_argument("--input-dir", type=Path, required=True, help="Clean WebCode2M root or its projects/ directory")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--edit-task-count", type=int, default=1)
    parser.add_argument("--repair-task-count", type=int, default=1)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-text-generation", action="store_true")
    parser.add_argument("--skip-image-generation", action="store_true")
    parser.add_argument("--skip-video-generation", action="store_true")
    parser.add_argument("--skip-editing", action="store_true")
    parser.add_argument("--skip-repair", action="store_true")
    parser.add_argument("--skip-validation", action="store_true")
    args = parser.parse_args()

    projects_dir = resolve_projects_dir(args.input_dir)
    overwrite = ["--overwrite"] if args.overwrite else []

    if not args.skip_text_generation:
        run_step([
            sys.executable,
            "WebCoding_Data/construct/construct_text_generation.py",
            "--input-dir",
            str(projects_dir),
            "--output-dir",
            str(args.output_dir / "text-generation"),
            "--limit",
            str(args.limit),
            *overwrite,
        ])

    if not args.skip_image_generation:
        run_step([
            sys.executable,
            "WebCoding_Data/construct/construct_image_generation.py",
            "--input-dir",
            str(projects_dir),
            "--output-dir",
            str(args.output_dir / "image-generation"),
            "--limit",
            str(args.limit),
            *overwrite,
        ])

    if not args.skip_video_generation:
        run_step([
            sys.executable,
            "WebCoding_Data/construct/construct_video_generation.py",
            "--input-dir",
            str(projects_dir),
            "--output-dir",
            str(args.output_dir / "video-generation"),
            "--limit",
            str(args.limit),
            *overwrite,
        ])

    if not args.skip_editing:
        text_edit_dir = args.output_dir / "text-editing"
        run_step([
            sys.executable,
            "WebCoding_Data/construct/construct_text_editing.py",
            "--input-dir",
            str(projects_dir),
            "--output-dir",
            str(text_edit_dir),
            "--limit",
            str(args.limit),
            "--task-count",
            str(args.edit_task_count),
            "--seed",
            str(args.seed),
            "--max-retries",
            str(args.max_retries),
            *overwrite,
        ])
        run_step([
            sys.executable,
            "WebCoding_Data/construct/construct_image_editing.py",
            "--input-dir",
            str(text_edit_dir),
            "--output-dir",
            str(args.output_dir / "image-editing"),
            "--limit",
            str(args.limit),
            *overwrite,
        ])

    if not args.skip_repair:
        text_repair_dir = args.output_dir / "text-repair"
        run_step([
            sys.executable,
            "WebCoding_Data/construct/construct_text_repair.py",
            "--input-dir",
            str(projects_dir),
            "--output-dir",
            str(text_repair_dir),
            "--limit",
            str(args.limit),
            "--task-count",
            str(args.repair_task_count),
            "--seed",
            str(args.seed),
            "--max-retries",
            str(args.max_retries),
            *overwrite,
        ])
        run_step([
            sys.executable,
            "WebCoding_Data/construct/construct_image_repair.py",
            "--input-dir",
            str(text_repair_dir),
            "--output-dir",
            str(args.output_dir / "image-repair"),
            "--limit",
            str(args.limit),
            *overwrite,
        ])

    if not args.skip_validation:
        run_step([
            sys.executable,
            "WebCoding_Data/construct/validate_webcode2m_task_dirs.py",
            "--root",
            str(args.output_dir),
            "--expected-per-task",
            str(args.limit),
            "--report",
            str(args.output_dir / "report.json"),
        ])


if __name__ == "__main__":
    main()
