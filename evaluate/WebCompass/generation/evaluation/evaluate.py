#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WebCompass Unified Evaluation Script

Evaluates generated websites from three input modalities:
- Text-to-Web
- Image-to-Web
- Video-to-Web

Supports two evaluation modes:
1. Checklist scoring (score_mode='checklist') - Uses checklist.json with score/max_score
2. LLM judge scoring (score_mode='llm_judge') - Uses LLM to compare reference vs generated images

Usage:
    python evaluate.py --text_dir /path/to/text_results --image_dir /path/to/image_results --video_dir /path/to/video_results
    python evaluate.py --root /path/to/results --score_mode llm_judge --model Gemini-3-Pro
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Add parent path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

try:
    from generation.call_model import call_api
except ImportError:
    try:
        from ..call_model import call_api
    except ImportError:
        call_api = None


# =============================================================================
# Constants
# =============================================================================

CHECKLIST_FILE_MERGED = "checklist.json"
CHECKLIST_FILES = [
    "checklist_Aesthetics.json",
    "checklist_Executability.json",
    "checklist_Interactivity.json",
]
CHECKLIST_FILES_LEGACY = [
    "checklist_aesthetics.json",
    "checklist_execution.json",
    "checklist_interaction.json",
]

# Category mappings (support both old and new naming)
CATEGORY_ALIASES = {
    # New names -> Canonical
    "runnability": "Runnability",
    "spec implementation": "Spec Implementation",
    "spec_implementation": "Spec Implementation",
    "specimplementation": "Spec Implementation",
    "design quality": "Design Quality",
    "design_quality": "Design Quality",
    "designquality": "Design Quality",
    # Old names -> Canonical (mapped to new)
    "execution": "Runnability",
    "executability": "Runnability",
    "interaction": "Spec Implementation",
    "interactivity": "Spec Implementation",
    "aesthetics": "Design Quality",
}

CANONICAL_CATEGORIES = ["Runnability", "Spec Implementation", "Design Quality"]

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class TaskScore:
    """Score for a single task/sample."""
    task_id: str
    modality: str  # 'text', 'image', 'video'
    path: str
    total_score: float
    max_score: float
    accuracy: Optional[float]
    harmonic_mean: Optional[float]
    by_category: Dict[str, Dict[str, float]] = field(default_factory=dict)
    num_items: int = 0
    error: Optional[str] = None


@dataclass
class EvalSummary:
    """Summary of evaluation results."""
    modality: str
    num_tasks: int
    avg_accuracy: Optional[float]
    avg_harmonic_mean: Optional[float]
    by_category_avg: Dict[str, float]
    task_scores: List[TaskScore]


# =============================================================================
# Utility Functions
# =============================================================================

def _safe_read_json(path: str) -> Optional[Any]:
    """Safely read JSON file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _to_float_or_none(v: Any) -> Optional[float]:
    """Convert value to float, return None if fails."""
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        if isinstance(v, float) and v != v:  # NaN
            return None
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def _normalize_category(cat: Any) -> str:
    """Normalize category name to canonical form."""
    if cat is None:
        return "unknown"
    s = str(cat).strip().lower()
    s = re.sub(r"[^a-z ]", "", s)
    return CATEGORY_ALIASES.get(s, cat)


def _harmonic_mean(values: List[float]) -> Optional[float]:
    """Calculate harmonic mean of values."""
    if not values:
        return None
    # Handle zeros by adding small epsilon
    adjusted = [max(v, 0.01) for v in values]
    denom = sum(1.0 / v for v in adjusted)
    if denom == 0:
        return None
    return len(adjusted) / denom


# =============================================================================
# Checklist Scoring
# =============================================================================

def score_task_from_checklist(task_dir: str, modality: str) -> Optional[TaskScore]:
    """Score a single task directory using checklist.json."""
    task_id = os.path.basename(os.path.normpath(task_dir))

    # Try to find checklist file
    checklist_path = os.path.join(task_dir, CHECKLIST_FILE_MERGED)
    data = _safe_read_json(checklist_path)

    if data is None:
        # Try split files
        for fname in CHECKLIST_FILES + CHECKLIST_FILES_LEGACY:
            fpath = os.path.join(task_dir, fname)
            if os.path.exists(fpath):
                data = _safe_read_json(fpath)
                if data:
                    break

    if not data:
        return None

    # Process checklist items
    items: List[Dict[str, Any]] = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        # Might be nested by category
        for key in CANONICAL_CATEGORIES + list(CATEGORY_ALIASES.keys()):
            if key in data and isinstance(data[key], list):
                items.extend(data[key])
        if not items and "problem_statement" in data:
            ps = data["problem_statement"]
            if isinstance(ps, list):
                items = ps

    if not items:
        return None

    total_score = 0.0
    max_score = 0.0
    by_category: Dict[str, Dict[str, float]] = {}
    item_ratios: List[float] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        score_v = _to_float_or_none(item.get("score"))
        max_v = _to_float_or_none(item.get("max_score"))

        if score_v is None or max_v is None or max_v <= 0:
            continue

        cat = _normalize_category(item.get("category"))

        total_score += score_v
        max_score += max_v

        if cat not in by_category:
            by_category[cat] = {"score": 0.0, "max_score": 0.0}
        by_category[cat]["score"] += score_v
        by_category[cat]["max_score"] += max_v

        ratio = score_v / max_v
        item_ratios.append(ratio)

    if max_score <= 0:
        return None

    accuracy = total_score / max_score if max_score > 0 else None
    hm = _harmonic_mean(item_ratios)

    return TaskScore(
        task_id=task_id,
        modality=modality,
        path=task_dir,
        total_score=total_score,
        max_score=max_score,
        accuracy=accuracy,
        harmonic_mean=hm,
        by_category=by_category,
        num_items=len(item_ratios),
    )


# =============================================================================
# LLM Judge Scoring (for Design Quality)
# =============================================================================

LLM_JUDGE_PROMPT = """
你现在是一名专业的网页 UI 复刻评审专家，专注于评估大模型或开发者的 UI 还原能力。

评分体系（总分 100 分）分为两个阶段：

第一阶段：核心基础分（保底权重 30%）
- 布局结构：页面整体排版、元素的相对位置、主次层级关系是否与原图一致
- 核心元素：关键按钮、标题文字、核心图形是否存在且形态正确
- 风格调性：整体色彩风格、质感是否与原图相符
若核心框架存在重大错误，直接判定为 0 分。

第二阶段：细节扣减分（区分权重 70%）
- 中度差异（-15分/处）：颜色色值明显偏差、字号/字重差异较大、按钮形状/圆角不符
- 轻度差异（-10分/处）：文字行高细微偏差、间距误差、阴影/渐变效果不完全一致
- 极微差异（-1分/处）：字体渲染的轻微锯齿、因截图压缩导致的色差

请对比【参考设计图】和【生成网页截图】，输出评分：

```json
{
    "score": <0-100的整数分数>,
    "reason": "<简要评价>"
}
```
"""


def _find_images_in_dir(folder: str) -> List[str]:
    """Find all image files in a directory."""
    if not os.path.isdir(folder):
        return []
    return [
        os.path.join(folder, f)
        for f in sorted(os.listdir(folder))
        if f.lower().endswith(IMAGE_EXTENSIONS)
    ]


def _extract_score_from_response(response: str) -> Optional[int]:
    """Extract score from LLM response."""
    if not response:
        return None

    # Try to find JSON block
    try:
        # Find JSON in response
        match = re.search(r'\{[^{}]*"score"\s*:\s*(\d+)[^{}]*\}', response, re.DOTALL)
        if match:
            return int(match.group(1))
    except Exception:
        pass

    # Fallback: find any number after "score"
    match = re.search(r'score["\s:]+(\d+)', response, re.IGNORECASE)
    if match:
        return int(match.group(1))

    return None


def score_task_with_llm_judge(
    task_dir: str,
    modality: str,
    model: str = "Gemini-3-Pro",
) -> Optional[TaskScore]:
    """Score a task using LLM to compare reference vs generated images."""
    if call_api is None:
        return None

    task_id = os.path.basename(os.path.normpath(task_dir))

    # Find reference images (screenshots/)
    ref_dir = os.path.join(task_dir, "screenshots")
    ref_images = _find_images_in_dir(ref_dir)

    # Find generated images (image/ or generated/)
    gen_dir = os.path.join(task_dir, "image")
    if not os.path.isdir(gen_dir):
        gen_dir = os.path.join(task_dir, "generated")
    gen_images = _find_images_in_dir(gen_dir)

    if not ref_images or not gen_images:
        return TaskScore(
            task_id=task_id,
            modality=modality,
            path=task_dir,
            total_score=0,
            max_score=100,
            accuracy=0,
            harmonic_mean=0,
            error="Missing reference or generated images",
        )

    # Call LLM with images
    try:
        # Use first reference and first generated image for now
        image_paths = [ref_images[0], gen_images[0]]
        response = call_api(LLM_JUDGE_PROMPT, model=model, image_path=image_paths)

        score = _extract_score_from_response(response)
        if score is None:
            score = 0

        return TaskScore(
            task_id=task_id,
            modality=modality,
            path=task_dir,
            total_score=float(score),
            max_score=100.0,
            accuracy=score / 100.0,
            harmonic_mean=score / 100.0,
            by_category={"Design Quality": {"score": float(score), "max_score": 100.0}},
            num_items=1,
        )
    except Exception as e:
        return TaskScore(
            task_id=task_id,
            modality=modality,
            path=task_dir,
            total_score=0,
            max_score=100,
            accuracy=0,
            harmonic_mean=0,
            error=str(e),
        )


# =============================================================================
# Directory Scanning
# =============================================================================

def iter_task_dirs(root: str) -> List[str]:
    """Iterate over task directories under root."""
    if not os.path.isdir(root):
        return []

    dirs = []
    for name in os.listdir(root):
        p = os.path.join(root, name)
        if os.path.isdir(p) and not name.startswith('.'):
            dirs.append(p)

    # Sort numerically if possible
    def sort_key(p):
        name = os.path.basename(p)
        try:
            return (0, int(name))
        except ValueError:
            return (1, name)

    return sorted(dirs, key=sort_key)


# =============================================================================
# Main Evaluation
# =============================================================================

def evaluate_modality(
    root: str,
    modality: str,
    score_mode: str = "checklist",
    model: str = "Gemini-3-Pro",
    workers: int = 4,
) -> EvalSummary:
    """Evaluate all tasks for a single modality."""
    task_dirs = iter_task_dirs(root)

    if not task_dirs:
        return EvalSummary(
            modality=modality,
            num_tasks=0,
            avg_accuracy=None,
            avg_harmonic_mean=None,
            by_category_avg={},
            task_scores=[],
        )

    scores: List[TaskScore] = []

    if score_mode == "checklist":
        # Simple sequential processing for checklist
        for task_dir in task_dirs:
            score = score_task_from_checklist(task_dir, modality)
            if score:
                scores.append(score)
    else:
        # Parallel processing for LLM judge
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(score_task_with_llm_judge, td, modality, model): td
                for td in task_dirs
            }
            for future in as_completed(futures):
                try:
                    score = future.result()
                    if score:
                        scores.append(score)
                except Exception as e:
                    print(f"Error processing {futures[future]}: {e}")

    if not scores:
        return EvalSummary(
            modality=modality,
            num_tasks=0,
            avg_accuracy=None,
            avg_harmonic_mean=None,
            by_category_avg={},
            task_scores=[],
        )

    # Compute averages
    valid_acc = [s.accuracy for s in scores if s.accuracy is not None]
    valid_hm = [s.harmonic_mean for s in scores if s.harmonic_mean is not None]

    avg_acc = sum(valid_acc) / len(valid_acc) if valid_acc else None
    avg_hm = sum(valid_hm) / len(valid_hm) if valid_hm else None

    # Compute by-category averages
    cat_scores: Dict[str, List[float]] = {}
    for s in scores:
        for cat, data in s.by_category.items():
            if data["max_score"] > 0:
                cat_scores.setdefault(cat, []).append(data["score"] / data["max_score"])

    by_category_avg = {
        cat: sum(vals) / len(vals) if vals else 0.0
        for cat, vals in cat_scores.items()
    }

    return EvalSummary(
        modality=modality,
        num_tasks=len(scores),
        avg_accuracy=avg_acc,
        avg_harmonic_mean=avg_hm,
        by_category_avg=by_category_avg,
        task_scores=scores,
    )


def print_summary(summary: EvalSummary) -> None:
    """Print evaluation summary."""
    print(f"\n{'='*60}")
    print(f"Modality: {summary.modality.upper()}")
    print(f"{'='*60}")
    print(f"Tasks evaluated: {summary.num_tasks}")

    if summary.avg_accuracy is not None:
        print(f"Average accuracy: {summary.avg_accuracy:.4f} ({summary.avg_accuracy*100:.2f}%)")
    if summary.avg_harmonic_mean is not None:
        print(f"Harmonic mean:    {summary.avg_harmonic_mean:.4f} ({summary.avg_harmonic_mean*100:.2f}%)")

    if summary.by_category_avg:
        print("\nBy Category:")
        for cat in CANONICAL_CATEGORIES:
            if cat in summary.by_category_avg:
                val = summary.by_category_avg[cat]
                print(f"  {cat}: {val:.4f} ({val*100:.2f}%)")


def save_results(
    summaries: List[EvalSummary],
    output_dir: str,
) -> None:
    """Save evaluation results to files."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Save detailed JSON
    results = {
        "timestamp": timestamp,
        "summaries": [
            {
                "modality": s.modality,
                "num_tasks": s.num_tasks,
                "avg_accuracy": s.avg_accuracy,
                "avg_harmonic_mean": s.avg_harmonic_mean,
                "by_category_avg": s.by_category_avg,
                "task_scores": [asdict(t) for t in s.task_scores],
            }
            for s in summaries
        ],
    }

    json_path = os.path.join(output_dir, f"eval_results_{timestamp}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nDetailed results saved to: {json_path}")

    # Save CSV summary
    csv_path = os.path.join(output_dir, f"eval_summary_{timestamp}.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "modality", "task_id", "accuracy", "harmonic_mean",
            "Runnability", "Spec Implementation", "Design Quality", "error"
        ])
        for s in summaries:
            for t in s.task_scores:
                row = [
                    t.modality,
                    t.task_id,
                    f"{t.accuracy:.4f}" if t.accuracy else "",
                    f"{t.harmonic_mean:.4f}" if t.harmonic_mean else "",
                ]
                for cat in CANONICAL_CATEGORIES:
                    if cat in t.by_category and t.by_category[cat]["max_score"] > 0:
                        val = t.by_category[cat]["score"] / t.by_category[cat]["max_score"]
                        row.append(f"{val:.4f}")
                    else:
                        row.append("")
                row.append(t.error or "")
                writer.writerow(row)
    print(f"CSV summary saved to: {csv_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="WebCompass Unified Evaluation Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Input directories
    parser.add_argument("--text_dir", type=str, help="Directory with text-to-web results")
    parser.add_argument("--image_dir", type=str, help="Directory with image-to-web results")
    parser.add_argument("--video_dir", type=str, help="Directory with video-to-web results")
    parser.add_argument("--root", type=str, help="Single root directory (auto-detect modality)")

    # Scoring options
    parser.add_argument(
        "--score_mode",
        choices=["checklist", "llm_judge"],
        default="checklist",
        help="Scoring mode: 'checklist' uses checklist.json, 'llm_judge' uses LLM comparison",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="Gemini-3-Pro",
        help="Model for LLM judge mode",
    )

    # Output options
    parser.add_argument("--output_dir", type=str, default="./eval_output", help="Output directory")
    parser.add_argument("--workers", type=int, default=4, help="Number of workers for parallel processing")
    parser.add_argument("--quiet", action="store_true", help="Suppress detailed output")

    args = parser.parse_args()

    # Collect directories to evaluate
    dirs_to_eval: List[Tuple[str, str]] = []  # (path, modality)

    if args.root:
        dirs_to_eval.append((args.root, "auto"))
    if args.text_dir:
        dirs_to_eval.append((args.text_dir, "text"))
    if args.image_dir:
        dirs_to_eval.append((args.image_dir, "image"))
    if args.video_dir:
        dirs_to_eval.append((args.video_dir, "video"))

    if not dirs_to_eval:
        parser.print_help()
        print("\nError: Please specify at least one directory to evaluate.")
        return 1

    # Evaluate each modality
    summaries: List[EvalSummary] = []

    for path, modality in dirs_to_eval:
        if not os.path.isdir(path):
            print(f"Warning: Directory not found: {path}")
            continue

        print(f"\nEvaluating {modality} from: {path}")
        summary = evaluate_modality(
            root=path,
            modality=modality,
            score_mode=args.score_mode,
            model=args.model,
            workers=args.workers,
        )
        summaries.append(summary)

        if not args.quiet:
            print_summary(summary)

    # Print overall summary
    if len(summaries) > 1:
        print(f"\n{'='*60}")
        print("OVERALL SUMMARY")
        print(f"{'='*60}")

        total_tasks = sum(s.num_tasks for s in summaries)
        all_acc = [s.avg_accuracy for s in summaries if s.avg_accuracy is not None]
        overall_acc = sum(all_acc) / len(all_acc) if all_acc else None

        print(f"Total tasks: {total_tasks}")
        if overall_acc is not None:
            print(f"Overall accuracy: {overall_acc:.4f} ({overall_acc*100:.2f}%)")

    # Save results
    if summaries:
        save_results(summaries, args.output_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
