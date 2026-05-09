"""
Video-generation data pipeline:
Record website interactions -> extract frames -> LLM generates description.

Supports vision mode (claude_sonnet4_5 from frames) or code mode (qwen3-coder-plus from source).

Usage:
    python -m data_pipeline.video_generate \
        --url https://example.com \
        --output data_pipeline/output/video_generate.jsonl \
        [--mode vision|code]

    python -m data_pipeline.video_generate \
        --video /path/to/video.mp4 --html_dir /path/to/source \
        --output data_pipeline/output/video_generate.jsonl
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from .common import (
    get_client, call_llm_text, call_llm_with_images, append_jsonl,
    TEXT_MODEL, VISION_MODEL,
)


CAPTION_FROM_VISION_PROMPT = """You are an expert web developer analyzing video frames of a website interaction.
The frames are in chronological order showing user interactions.

Write a detailed web design document describing:
1. Overall layout and visual design
2. All UI components
3. Interactive behavior shown across frames (clicks, transitions, animations)
4. State changes between frames
5. Colors, typography, spacing
6. Responsive behavior if visible

Focus on interactive/dynamic aspects since this is for a video-generation task.
Do NOT reference "frames" — write as requirements.
Output ONLY the design document."""


CAPTION_FROM_CODE_PROMPT = """You are an expert web developer. Below is the source code of a website
recorded as a video demonstrating interactive features.

Write a detailed web design document describing:
1. Overall layout and visual design
2. All UI components
3. Interactive behavior (infer from JS: click handlers, animations, transitions)
4. State changes (menu toggle, modal show/hide, etc.)
5. Colors, typography, spacing
6. Responsive behavior

Focus on interactive/dynamic aspects since this is for a video-generation task.
Write as requirements — do NOT reference source code.
Output ONLY the design document.

Source code:
---
{source_code}
---"""


CHECKLIST_PROMPT = """You are an expert web QA engineer. Given the following web design document
with interactive behaviors, generate an evaluation checklist in JSON format.

Categories:
1. "Runnability" (1 item, max_score: 10)
2. "Spec Implementation" (5-8 items, total ~65) — include interaction/animation checks
3. "Design Quality" (2-3 items, total ~25)

Each item: {{"task", "category", "operation_sequence", "expected_result", "criteria", "max_score"}}

Output ONLY a valid JSON array. No fences, no explanation.

Design document:
---
{document}
---"""


def extract_frames(video_path: str, output_dir: str, fps: float = 2.0, max_frames: int = 30) -> list[str]:
    """Extract frames from a video using ffmpeg."""
    os.makedirs(output_dir, exist_ok=True)
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True, check=True,
        )
        duration = float(result.stdout.strip())
    except Exception:
        duration = 30.0

    if int(duration * fps) > max_frames:
        fps = max_frames / duration

    output_pattern = os.path.join(output_dir, "frame_%04d.jpg")
    subprocess.run(
        ["ffmpeg", "-i", video_path, "-vf", f"fps={fps}", "-q:v", "2", "-y", output_pattern],
        capture_output=True, check=True,
    )

    frames = sorted(Path(output_dir).glob("frame_*.jpg"))
    if len(frames) > max_frames:
        step = len(frames) / max_frames
        indices = [int(i * step) for i in range(max_frames)]
        frames = [frames[i] for i in indices]
    return [str(f) for f in frames]


def record_website(url: str, output_dir: str) -> tuple[str, str]:
    """Record a website interaction. Returns (video_path, page_html)."""
    os.makedirs(output_dir, exist_ok=True)
    page_html = ""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=output_dir,
            record_video_size={"width": 1280, "height": 720},
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            print(f"  [WARN] Page load issue: {e}")

        page.wait_for_timeout(2000)
        page_html = page.content()

        # Scroll through
        for i in range(5):
            page.evaluate(f"window.scrollTo(0, document.body.scrollHeight * {(i+1)/5})")
            page.wait_for_timeout(1500)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(1000)

        # Click interactive elements
        clickable = page.query_selector_all("button, a.button, .btn, [role='button']")
        for el in clickable[:3]:
            try:
                if el.is_visible():
                    el.click(timeout=2000)
                    page.wait_for_timeout(1500)
            except Exception:
                pass

        page.wait_for_timeout(1000)
        video_path = page.video.path()
        context.close()
        browser.close()

    return video_path, page_html


def collect_source_for_prompt(html_dir: str, max_chars: int = 30000) -> str:
    """Collect source files from a directory for prompt."""
    source_exts = {".html", ".css", ".js"}
    parts = []
    total = 0
    root = Path(html_dir)
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in source_exts or f.stat().st_size > 500_000:
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        header = f"\n=== {f.relative_to(root)} ===\n"
        if total + len(header) + len(content) > max_chars:
            remaining = max_chars - total - len(header) - 50
            if remaining > 200:
                parts.append(header + content[:remaining] + "\n... (truncated)")
            break
        parts.append(header + content)
        total += len(header) + len(content)
    return "".join(parts)


def parse_json_from_response(response: str) -> list:
    response = response.strip()
    if response.startswith("```"):
        lines = response.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        response = "\n".join(lines)
    return json.loads(response)


def process_video(
    video_path: str,
    source_code: str,
    instance_id: str,
    client,
    output_jsonl: str,
    frames_base: str,
    mode: str = "vision",
):
    print(f"\n--- Processing video (id={instance_id}) ---")

    print(f"[1/3] Extracting frames...")
    frames_dir = os.path.join(frames_base, instance_id)
    frames = extract_frames(video_path, frames_dir)
    print(f"  -> {len(frames)} frames")
    if not frames:
        print(f"  [SKIP] No frames")
        return None

    print(f"[2/3] Generating description...")
    if mode == "vision":
        # Send up to 10 frames to vision model (cost control)
        frames_to_send = frames[:10] if len(frames) > 10 else frames
        description = call_llm_with_images(
            client, VISION_MODEL, CAPTION_FROM_VISION_PROMPT, frames_to_send
        )
    else:
        prompt = CAPTION_FROM_CODE_PROMPT.format(source_code=source_code[:30000])
        description = call_llm_text(client, TEXT_MODEL, prompt)
    print(f"  -> Description: {len(description)} chars")

    print(f"[3/3] Generating checklist ({TEXT_MODEL})...")
    checklist = parse_json_from_response(
        call_llm_text(client, TEXT_MODEL, CHECKLIST_PROMPT.format(document=description))
    )
    print(f"  -> {len(checklist)} checklist items")

    item = {
        "repo": "claude/webcoding",
        "instance_id": instance_id,
        "base_commit": "main",
        "problem_statement": checklist,
        "meta": {"class": "Web Development", "difficulty": "medium"},
        "working_dir": "/testbed",
        "instruction": description,
    }
    append_jsonl(output_jsonl, item)
    print(f"  -> Saved to {output_jsonl}")
    return item


def main():
    parser = argparse.ArgumentParser(description="Video-generation data pipeline")
    parser.add_argument("--video", default=None)
    parser.add_argument("--url", default=None)
    parser.add_argument("--html_dir", default=None, help="Source dir (when using --video)")
    parser.add_argument("--output", default="data_pipeline/output/video_generate.jsonl")
    parser.add_argument("--frames_dir", default="data_pipeline/output/frames")
    parser.add_argument("--record_dir", default="data_pipeline/output/recordings")
    parser.add_argument("--instance_id", default=None)
    parser.add_argument("--mode", default="vision", choices=["vision", "code"])
    args = parser.parse_args()

    if not args.video and not args.url:
        print("Error: Must provide either --video or --url")
        sys.exit(1)

    client = get_client()

    if args.url:
        parsed = urlparse(args.url)
        domain = parsed.netloc.replace("www.", "").replace(".", "_")
        instance_id = args.instance_id or f"vid_{domain}"
        print(f"Recording website: {args.url}")
        video_path, page_html = record_website(args.url, args.record_dir)
        source_code = page_html
        print(f"  -> Video saved to {video_path}")
    else:
        video_path = args.video
        instance_id = args.instance_id or Path(video_path).stem
        if args.html_dir:
            source_code = collect_source_for_prompt(args.html_dir)
        else:
            print("Error: --html_dir required when using --video")
            sys.exit(1)

    result = process_video(
        video_path=video_path,
        source_code=source_code,
        instance_id=instance_id,
        client=client,
        output_jsonl=args.output,
        frames_base=args.frames_dir,
        mode=args.mode,
    )
    if result:
        print(f"\nDone! Instance {instance_id} saved.")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
