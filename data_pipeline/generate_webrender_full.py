from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image
from playwright.sync_api import sync_playwright

VIEWPORTS = [
    ("desktop", 1920, 1080),
    ("tablet", 768, 1024),
    ("mobile", 375, 812),
]

TEXT_PRD_PROMPT = """You are writing a complete product requirements/design document for a web coding benchmark task.
You are given full-page screenshots from ALL HTML pages in one website/project, across desktop/tablet/mobile when available.
Write a comprehensive PRD-like implementation instruction for a developer to recreate the entire project, not just one page.

Required style:
- Align with WebCompass generation instructions: clear, concrete, implementation-facing, and organized.
- Do not mention screenshots, images, reverse construction, or the source website.
- Cover every page represented in the inputs, including page names, layout, visible content, navigation, forms, tables, media, footer, responsive behavior, and interactions implied by the UI.
- If multiple pages share components, describe the shared shell and then page-specific content.
- Be exhaustive and specific, but use natural design language rather than CSS pixel trivia.

Output exactly these sections:
# Web project overview
# Global layout and navigation
# Page-by-page requirements
# Interaction requirements
# Responsive and visual design requirements
# Content and asset requirements
"""

CHUNK_PROMPT = (
    TEXT_PRD_PROMPT
    + "\nFocus only on the pages/images in this batch. Produce detailed notes that will later be merged."
)

MERGE_PROMPT = """Merge the following batch-level website notes into one final, comprehensive WebCompass-style PRD/instruction.
Do not mention batches, screenshots, images, or reverse construction.
Keep all distinct pages and requirements. Use exactly these sections:
# Web project overview
# Global layout and navigation
# Page-by-page requirements
# Interaction requirements
# Responsive and visual design requirements
# Content and asset requirements

Batch notes:
---
{notes}
---
"""


def safe_name(value: str) -> str:
    value = str(value).replace(os.sep, "__")
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_") or "page"


def append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def load_done(manifest: Path) -> set[str]:
    done: set[str] = set()
    if not manifest.exists():
        return done
    for line in manifest.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("status") == "ok":
            done.add(str(obj.get("instance_id")))
    return done


def find_html_pages(project_dir: Path) -> List[Path]:
    pages: List[Path] = []
    for page in sorted(project_dir.rglob("*.html")):
        rel_parts = page.relative_to(project_dir).parts
        if any(part.lower() in {"resources", "assets", "static", "node_modules"} for part in rel_parts[:-1]):
            continue
        pages.append(page)
    index = project_dir / "index.html"
    if index.exists() and index not in pages:
        pages.insert(0, index)
    return pages


def route_local_only(route) -> None:
    url = route.request.url
    if url.startswith(("file://", "data:", "blob:")):
        route.continue_()
    else:
        route.abort("connectionfailed")


def screenshot_project(project_dir: Path, out_dir: Path) -> List[Dict[str, str]]:
    pages = find_html_pages(project_dir)
    if not pages:
        raise RuntimeError("no html pages found")

    shot_root = out_dir / "screenshots"
    if shot_root.exists():
        shutil.rmtree(shot_root)
    shot_root.mkdir(parents=True, exist_ok=True)

    records: List[Dict[str, str]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for html in pages:
            rel = html.relative_to(project_dir).as_posix()
            page_key = safe_name(rel[:-5] if rel.lower().endswith(".html") else rel)
            for vp_name, width, height in VIEWPORTS:
                page = browser.new_page(viewport={"width": width, "height": height})
                page.route("**/*", route_local_only)
                try:
                    page.goto("file://" + str(html.resolve()), wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(1000)
                    dest = shot_root / f"{page_key}__{vp_name}.jpg"
                    page.screenshot(path=str(dest), full_page=True, type="jpeg", quality=82, timeout=90000)
                    records.append({"page": rel, "viewport": vp_name, "path": str(dest.relative_to(out_dir))})
                finally:
                    page.close()
        browser.close()
    return records


def encode_image_for_api(path: Path, max_width: int = 1200, max_bytes: int = 3_500_000) -> str:
    img = Image.open(path).convert("RGB")
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, max(1, int(img.height * ratio))))

    tmp = Path(str(path) + ".api.jpg")
    quality = 82
    while True:
        img.save(tmp, "JPEG", quality=quality, optimize=True)
        if tmp.stat().st_size <= max_bytes or quality <= 50:
            data = tmp.read_bytes()
            tmp.unlink(missing_ok=True)
            return base64.b64encode(data).decode("utf-8")
        quality -= 8


def call_vlm(
    client: OpenAI,
    model: str,
    prompt: str,
    image_paths: List[Path] | None = None,
    max_tokens: int = 4096,
) -> str:
    if image_paths:
        content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image_path in image_paths:
            b64 = encode_image_for_api(image_path)
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        messages = [{"role": "user", "content": content}]
    else:
        messages = [{"role": "user", "content": prompt}]

    response = client.chat.completions.create(model=model, messages=messages, max_tokens=max_tokens)
    return response.choices[0].message.content or ""


def generate_prd_from_screenshots(out_dir: Path, screenshots: List[Dict[str, str]]) -> str:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    client = OpenAI(
        base_url=os.environ["VISION_OPENAI_BASE_URL"],
        api_key=os.environ["VISION_OPENAI_API_KEY"],
        timeout=180.0,
    )
    model = os.environ.get("VISION_MODEL", "qwen3-vl-235b-a22b-instruct")

    paths = [out_dir / shot["path"] for shot in screenshots]
    notes: List[str] = []
    chunk_size = 9
    for start in range(0, len(paths), chunk_size):
        chunk = paths[start : start + chunk_size]
        labels = "\n".join(
            f"- {screenshots[idx]['page']} ({screenshots[idx]['viewport']})"
            for idx in range(start, min(start + chunk_size, len(paths)))
        )
        prompt = CHUNK_PROMPT + "\n\nPages in this batch:\n" + labels
        notes.append(call_vlm(client, model, prompt, chunk, max_tokens=4096))

    if len(notes) == 1:
        return notes[0]
    return call_vlm(client, model, MERGE_PROMPT.format(notes="\n\n".join(notes)), None, max_tokens=8192)


def record_project(project_dir: Path, out_dir: Path) -> List[Dict[str, Any]]:
    pages = find_html_pages(project_dir)
    if not pages:
        raise RuntimeError("no html pages found")

    video_root = out_dir / "videos"
    if video_root.exists():
        shutil.rmtree(video_root)
    video_root.mkdir(parents=True, exist_ok=True)

    records: List[Dict[str, Any]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for html in pages:
            rel = html.relative_to(project_dir).as_posix()
            page_key = safe_name(rel[:-5] if rel.lower().endswith(".html") else rel)
            record_dir = video_root / page_key
            record_dir.mkdir(parents=True, exist_ok=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                record_video_dir=str(record_dir),
                record_video_size={"width": 1280, "height": 720},
            )
            page = context.new_page()
            page.route("**/*", route_local_only)
            start = time.time()
            try:
                page.goto("file://" + str(html.resolve()), wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1200)
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(500)
                scroll_height = page.evaluate(
                    "Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
                )
                y = 0
                step = 468
                while y < scroll_height:
                    y = min(scroll_height, y + step)
                    page.evaluate("scrollY => window.scrollTo(0, scrollY)", y)
                    page.wait_for_timeout(650)
                    scroll_height = page.evaluate(
                        "Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
                    )
                page.wait_for_timeout(800)
            finally:
                video = page.video
                context.close()
                if video:
                    raw_video = Path(video.path())
                    if raw_video.exists():
                        final = video_root / f"{page_key}.webm"
                        if final.exists():
                            final.unlink()
                        shutil.move(str(raw_video), final)
                        records.append(
                            {
                                "page": rel,
                                "path": str(final.relative_to(out_dir)),
                                "duration_sec": round(time.time() - start, 2),
                            }
                        )
        browser.close()
    return records


def process_project(task: str, project_dir: Path, output_dir: Path) -> Dict[str, Any]:
    instance_id = project_dir.name
    item_dir = output_dir / "assets" / instance_id
    item_dir.mkdir(parents=True, exist_ok=True)

    item: Dict[str, Any] = {
        "repo": "claude/webcoding",
        "instance_id": instance_id,
        "base_commit": "main",
        "meta": {"class": "Web Development", "difficulty": "medium"},
        "working_dir": "/testbed",
    }

    if task == "text":
        screenshots = screenshot_project(project_dir, item_dir)
        item["instruction"] = generate_prd_from_screenshots(item_dir, screenshots)
        return item
    if task == "image":
        item["screenshots"] = screenshot_project(project_dir, item_dir)
        return item
    if task == "video":
        item["videos"] = record_project(project_dir, item_dir)
        return item
    raise ValueError(task)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--page_dirs", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--task", required=True, choices=["text", "image", "video"])
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    root = Path(args.page_dirs)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_jsonl = output_dir / f"{args.task}_generation.jsonl"
    manifest = output_dir / f"manifest_{args.task}.jsonl"
    done = load_done(manifest)

    projects = sorted([p for p in root.iterdir() if p.is_dir() and p.name not in done])
    if args.limit > 0:
        projects = projects[: args.limit]
    print(f"task={args.task} remaining={len(projects)} done={len(done)}")

    for idx, project in enumerate(projects, 1):
        status = "error"
        error = None
        try:
            item = process_project(args.task, project, output_dir)
            append_jsonl(output_jsonl, item)
            status = "ok"
            print(f"[{idx}/{len(projects)}] OK {project.name}")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            print(f"[{idx}/{len(projects)}] ERROR {project.name}: {error}")
        append_jsonl(
            manifest,
            {
                "instance_id": project.name,
                "task": args.task,
                "status": status,
                "error": error,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            },
        )


if __name__ == "__main__":
    main()
