"""
Batch generate queries for web pages using reverse construction.

For each page directory, generates a design document (instruction) and
evaluation checklist (problem_statement) for SFT training.

Supports three task types:
- text: design document + checklist from source code
- image: screenshots + checklist (no instruction field)
- video: recorded interaction + frames + design document + checklist

Usage:
    # Test with 1 page
    python -m data_pipeline.batch_generate \
        --page_dirs data_pipeline/output/github_pages \
        --output_dir data_pipeline/output/generate \
        --task text --mode code --limit 1

    # Batch run
    python -m data_pipeline.batch_generate \
        --page_dirs /path/to/pages \
        --output_dir data_pipeline/output/generate \
        --task text --mode code --limit 0
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from .common import (
    get_client, call_llm_text, call_llm_with_images, append_jsonl, load_env,
    TEXT_MODEL, VISION_MODEL,
)
from .image_reverse import (
    collect_source_files, format_source_for_prompt,
    take_screenshots,
    CAPTION_FROM_CODE_PROMPT as TEXT_CAPTION_CODE,
    CAPTION_FROM_VISION_PROMPT as TEXT_CAPTION_VISION,
)
from .video_generate import (
    CAPTION_FROM_CODE_PROMPT as VIDEO_CAPTION_CODE,
    CAPTION_FROM_VISION_PROMPT as VIDEO_CAPTION_VISION,
    extract_frames,
)


# ---------------------------------------------------------------------------
# Processing functions
# ---------------------------------------------------------------------------

def process_text(page_dir, instance_id, client, mode, output_jsonl, screenshots_dir, meta):
    """Generate text-generation data item."""
    src_files = collect_source_files(page_dir)
    if not src_files:
        return None

    # Generate design document
    if mode == "vision":
        html_path = _find_html(page_dir)
        if not html_path:
            return None
        shot_dir = os.path.join(screenshots_dir, instance_id)
        screenshots = take_screenshots(html_path, shot_dir)
        description = call_llm_with_images(
            client, VISION_MODEL, TEXT_CAPTION_VISION, screenshots
        )
    else:
        source_text = format_source_for_prompt(src_files)
        prompt = TEXT_CAPTION_CODE.format(source_code=source_text)
        description = call_llm_text(client, TEXT_MODEL, prompt)

    if not description or len(description) < 100:
        return None

    item = {
        "repo": "claude/webcoding",
        "instance_id": str(instance_id),
        "base_commit": "main",
        "instruction": description,
        "meta": {"class": meta.get("industry", "Web Development"), "difficulty": "medium"},
        "working_dir": "/testbed",
    }
    append_jsonl(output_jsonl, item)
    return item


def process_image(page_dir, instance_id, client, mode, output_jsonl, screenshots_dir, meta):
    """Generate image-generation data item (screenshots + checklist, no instruction)."""
    html_path = _find_html(page_dir)
    if not html_path:
        return None

    # Take screenshots
    shot_dir = os.path.join(screenshots_dir, instance_id)
    screenshots = take_screenshots(html_path, shot_dir)
    screenshot_names = [Path(s).name for s in screenshots]

    item = {
        "repo": "claude/webcoding",
        "instance_id": str(instance_id),
        "base_commit": "main",
        "meta": {"class": meta.get("industry", "image_genration"), "difficulty": "medium"},
        "working_dir": "/testbed",
        "screenshots": screenshot_names,
    }
    append_jsonl(output_jsonl, item)
    return item


def process_video(page_dir, instance_id, client, mode, output_jsonl, screenshots_dir, meta):
    """Generate video-generation data item."""
    src_files = collect_source_files(page_dir)
    if not src_files:
        return None

    # Generate design document (emphasizing interaction)
    if mode == "vision":
        # Record video + extract frames
        html_path = _find_html(page_dir)
        if not html_path:
            return None
        vid_dir = os.path.join(screenshots_dir, f"{instance_id}_video")
        os.makedirs(vid_dir, exist_ok=True)
        from .video_generate import record_website
        video_path = record_website(f"file://{os.path.abspath(html_path)}", vid_dir)
        if not video_path:
            return None
        frames_dir = os.path.join(vid_dir, "frames")
        frames = extract_frames(video_path, frames_dir, fps=2.0, max_frames=10)
        description = call_llm_with_images(
            client, VISION_MODEL, VIDEO_CAPTION_VISION, frames[:10]
        )
    else:
        source_text = format_source_for_prompt(src_files)
        prompt = VIDEO_CAPTION_CODE.format(source_code=source_text)
        description = call_llm_text(client, TEXT_MODEL, prompt)

    if not description or len(description) < 100:
        return None

    item = {
        "repo": "claude/webcoding",
        "instance_id": str(instance_id),
        "base_commit": "main",
        "instruction": description,
        "meta": {"class": meta.get("industry", "Web Development"), "difficulty": "medium"},
        "working_dir": "/testbed",
    }
    append_jsonl(output_jsonl, item)
    return item


def _find_html(page_dir):
    """Find index.html or first .html file."""
    index = os.path.join(page_dir, "index.html")
    if os.path.exists(index):
        return index
    html_files = list(Path(page_dir).glob("*.html"))
    return str(html_files[0]) if html_files else None


# ---------------------------------------------------------------------------
# Resume support
# ---------------------------------------------------------------------------

def load_processed(manifest_path):
    """Load already-processed instance IDs from manifest."""
    processed = set()
    if not os.path.exists(manifest_path):
        return processed
    with open(manifest_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                processed.add(obj["instance_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return processed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

TASK_PROCESSORS = {
    "text": process_text,
    "image": process_image,
    "video": process_video,
}


def main():
    parser = argparse.ArgumentParser(description="Batch generate queries for web pages")
    parser.add_argument("--page_dirs", required=True,
                        help="Parent directory containing page subdirectories")
    parser.add_argument("--output_dir", default="data_pipeline/output/generate",
                        help="Output directory for JSONL and screenshots")
    parser.add_argument("--task", required=True, choices=["text", "image", "video"],
                        help="Task type to generate")
    parser.add_argument("--mode", default="code", choices=["vision", "code"],
                        help="code=qwen3-coder-plus (cheap), vision=claude_sonnet4_5 (expensive)")
    parser.add_argument("--manifest", default=None,
                        help="Manifest JSONL for resume support (default: output_dir/manifest_<task>.jsonl)")
    parser.add_argument("--limit", type=int, default=2,
                        help="Max pages to process (0=unlimited)")
    args = parser.parse_args()

    load_env()
    client = get_client()

    os.makedirs(args.output_dir, exist_ok=True)
    output_jsonl = os.path.join(args.output_dir, f"{args.task}_generation.jsonl")
    screenshots_dir = os.path.join(args.output_dir, "screenshots")
    manifest = args.manifest or os.path.join(args.output_dir, f"manifest_{args.task}.jsonl")

    processed = load_processed(manifest)
    print(f"Resuming: {len(processed)} already processed")

    # Discover page directories
    page_dirs_root = Path(args.page_dirs)
    if not page_dirs_root.is_dir():
        print(f"Error: {args.page_dirs} is not a directory")
        sys.exit(1)

    candidates = sorted([
        d for d in page_dirs_root.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    ])
    print(f"Total page directories: {len(candidates)}")

    # Filter already processed
    remaining = [d for d in candidates if d.name not in processed]
    print(f"Remaining: {len(remaining)}")

    limit = args.limit if args.limit > 0 else len(remaining)
    processor = TASK_PROCESSORS[args.task]

    total = 0
    ok = 0
    errors = 0

    for page_dir in remaining:
        if total >= limit:
            break

        total += 1
        instance_id = page_dir.name
        print(f"\n[{total}/{limit}] {instance_id}")

        try:
            result = processor(
                str(page_dir), instance_id, client, args.mode,
                output_jsonl, screenshots_dir,
                meta={"industry": "Web Development"},
            )
            if result:
                ok += 1
                print(f"  [OK] instruction={len(result.get('instruction', ''))} chars, "
                      f"checklist={len(result.get('problem_statement', []))} items")
            else:
                print(f"  [SKIP] No result")

        except Exception as e:
            errors += 1
            print(f"  [ERROR] {e}")

        # Write manifest
        append_jsonl(manifest, {
            "instance_id": instance_id,
            "task": args.task,
            "status": "ok" if result else "skip",
            "timestamp": datetime.now().isoformat(),
        })

    print(f"\n=== Summary ===")
    print(f"Processed: {total}")
    print(f"OK: {ok}")
    print(f"Errors: {errors}")
    print(f"Output: {output_jsonl}")


if __name__ == "__main__":
    main()
