#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

TASK_NAMES = ["text-generation", "image-generation", "video-generation", "text-editing", "text-repair"]


def resolve_projects_dir(input_dir: Path) -> Path:
    projects = input_dir / "projects"
    return projects if projects.exists() else input_dir


def partition_projects(
    projects_dir: Path, partition_str: str, seed: int,
) -> dict[str, list[Path]]:
    """Split projects into non-overlapping groups for each task type."""
    projects = sorted(
        d for d in projects_dir.iterdir()
        if d.is_dir() and (d / "index.html").exists()
    )
    rng = random.Random(seed)
    rng.shuffle(projects)

    weights = [int(x) for x in partition_str.split(":")]
    if len(weights) != 5:
        raise ValueError(f"--partition must have 5 colon-separated weights, got {len(weights)}")
    total_w = sum(weights)

    groups: dict[str, list[Path]] = {}
    start = 0
    for i, (task, w) in enumerate(zip(TASK_NAMES, weights)):
        if i < len(weights) - 1:
            end = start + len(projects) * w // total_w
        else:
            end = len(projects)
        groups[task] = projects[start:end]
        start = end
    return groups


def create_partition_dir(output_dir: Path, task_name: str, projects: list[Path]) -> Path:
    """Create a symlink directory pointing to the assigned projects."""
    part_dir = output_dir / ".partitions" / task_name
    if part_dir.exists():
        shutil.rmtree(part_dir)
    part_dir.mkdir(parents=True)
    for p in projects:
        link = part_dir / p.name
        link.symlink_to(p.resolve())
    return part_dir


def run_step(args: list[str]) -> None:
    print("+ " + " ".join(args), flush=True)
    subprocess.run(args, cwd=REPO_ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="WebCode2M dataset driver with project partitioning. "
        "Each project is assigned to exactly one task type."
    )
    parser.add_argument("--input-dir", type=Path, required=True, help="Clean WebCode2M root or its projects/ directory")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--partition", default="2:2:1:2:2",
                        help="Partition ratio for text-gen:image-gen:video-gen:text-edit:text-repair (default: 2:2:1:2:2)")
    parser.add_argument("--edit-min-tasks", type=int, default=4)
    parser.add_argument("--edit-max-tasks", type=int, default=12)
    parser.add_argument("--repair-min-tasks", type=int, default=4)
    parser.add_argument("--repair-max-tasks", type=int, default=12)
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
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # --- Partition projects so each is used by exactly one task type ---
    groups = partition_projects(projects_dir, args.partition, args.seed)
    print(f"Project partition (seed={args.seed}, ratio={args.partition}):")
    for task, projs in groups.items():
        print(f"  {task}: {len(projs)} projects")
    print(f"  total: {sum(len(p) for p in groups.values())} projects", flush=True)

    partition_dirs: dict[str, Path] = {}
    for task, projs in groups.items():
        if projs:
            partition_dirs[task] = create_partition_dir(args.output_dir, task, projs)

    # --- Run each task type on its own partition ---
    if not args.skip_text_generation and "text-generation" in partition_dirs:
        run_step([
            sys.executable,
            "WebCoding_Data/construct/construct_text_generation.py",
            "--input-dir",
            str(partition_dirs["text-generation"]),
            "--output-dir",
            str(args.output_dir / "text-generation"),
            "--limit",
            str(args.limit),
            *overwrite,
        ])

    if not args.skip_image_generation and "image-generation" in partition_dirs:
        run_step([
            sys.executable,
            "WebCoding_Data/construct/construct_image_generation.py",
            "--input-dir",
            str(partition_dirs["image-generation"]),
            "--output-dir",
            str(args.output_dir / "image-generation"),
            "--limit",
            str(args.limit),
            *overwrite,
        ])

    if not args.skip_video_generation and "video-generation" in partition_dirs:
        run_step([
            sys.executable,
            "WebCoding_Data/construct/construct_video_generation.py",
            "--input-dir",
            str(partition_dirs["video-generation"]),
            "--output-dir",
            str(args.output_dir / "video-generation"),
            "--limit",
            str(args.limit),
            *overwrite,
        ])

    if not args.skip_editing and "text-editing" in partition_dirs:
        text_edit_dir = args.output_dir / "text-editing"
        run_step([
            sys.executable,
            "WebCoding_Data/construct/construct_text_editing.py",
            "--input-dir",
            str(partition_dirs["text-editing"]),
            "--output-dir",
            str(text_edit_dir),
            "--limit",
            str(args.limit),
            "--min-tasks",
            str(args.edit_min_tasks),
            "--max-tasks",
            str(args.edit_max_tasks),
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

    if not args.skip_repair and "text-repair" in partition_dirs:
        text_repair_dir = args.output_dir / "text-repair"
        run_step([
            sys.executable,
            "WebCoding_Data/construct/construct_text_repair.py",
            "--input-dir",
            str(partition_dirs["text-repair"]),
            "--output-dir",
            str(text_repair_dir),
            "--limit",
            str(args.limit),
            "--min-tasks",
            str(args.repair_min_tasks),
            "--max-tasks",
            str(args.repair_max_tasks),
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
