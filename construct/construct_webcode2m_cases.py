#!/usr/bin/env python3
"""Build seven WebCompass-style prototype case sets from cleaned WebCode2M projects.

The output is intentionally lightweight and reproducible: no LLM calls are
required. Text instructions are heuristic summaries from each page, image/video
inputs are rendered from the cleaned local projects, and edit/repair pairs use
deterministic transformations so every case has a concrete src/dst.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path
import sys
from typing import Any

from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from WebCoding_Data.construct.construct_common import (
    collect_resources,
    read_code_bundle,
    safe_write_json,
    screenshot_project_to_dir,
)


TASKS = [
    "text-generation",
    "image-generation",
    "video-generation",
    "text-editing",
    "image-editing",
    "text-repair",
    "image-repair",
]

EDIT_DESCRIPTIONS = [
    "Add a compact newsletter signup band near the end of the page with an email input, a clear submit button, and a short privacy note. Keep the styling consistent with the existing page.",
    "Add a featured highlights section with three cards summarizing the main services or content areas already implied by the page.",
    "Add a sticky back-to-top button that appears in the lower-right corner and smoothly scrolls to the top when clicked.",
    "Add a responsive contact callout with phone, email, and location rows using local inline icons or CSS shapes rather than external icon URLs.",
    "Add a lightweight tabbed information block with three tabs and keyboard-accessible buttons.",
    "Add a search/filter bar above the main list or content area and make matching cards/items fade visually when filtered.",
    "Add a compact FAQ accordion near the bottom of the page with three questions and accessible expand/collapse behavior.",
    "Add a small notification banner at the top of the page with a dismiss button that stores its dismissed state in localStorage.",
    "Add hover and focus states to the main call-to-action links, including visible keyboard focus rings.",
    "Add a responsive footer utility strip with secondary navigation links and a short brand statement.",
]

REPAIR_DESCRIPTIONS = [
    "Fix distorted images so they preserve their aspect ratio and do not stretch horizontally.",
    "Fix the page overflow caused by oversized visual areas on small screens.",
    "Fix the main content being partially hidden by an overly aggressive fixed header style.",
    "Fix text blocks that became cramped and difficult to read after spacing was reduced.",
    "Fix interactive buttons that lost their visible focus state.",
    "Fix cards that overlap because the grid columns are too narrow.",
    "Fix the footer spacing so links no longer collide on mobile.",
    "Fix decorative images that are missing accessible alt text.",
    "Fix form controls that are too short and hard to tap on mobile.",
    "Fix the page background and foreground contrast after an accidental low-contrast style override.",
]


def text_content(project_dir: Path) -> tuple[str, list[str]]:
    html = (project_dir / "index.html").read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string if soup.title and soup.title.string else project_dir.name).strip()
    headings = []
    for tag in soup.find_all(["h1", "h2", "h3"]):
        text = " ".join(tag.get_text(" ", strip=True).split())
        if text and text not in headings:
            headings.append(text)
        if len(headings) >= 8:
            break
    return title, headings


def build_instruction(project_dir: Path) -> str:
    title, headings = text_content(project_dir)
    heading_text = "; ".join(headings[:6]) if headings else "a header, main content sections, visual media areas, and footer content"
    return (
        f"Build a clean, self-contained single-page website matching the page titled '{title}'. "
        f"Preserve the visible content hierarchy, including these major areas: {heading_text}. "
        "Use local assets for all icons and media, keep the page offline-renderable, maintain the original visual density and typography tone, "
        "and make the layout responsive for desktop, tablet, and mobile. Do not rely on remote images, CDNs, analytics scripts, or external fonts."
    )


def case_info(instance_id: str, task: str, source_project: Path) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "task": task,
        "task_family": task.split("-", 1)[-1] if "-" in task else task,
        "instruction": "",
        "description": "",
        "task_type": [],
        "src_code": [],
        "dst_code": [],
        "src_screenshot": [],
        "dst_screenshot": [],
        "input_screenshots": [],
        "input_videos": [],
        "label_modified_files": [],
        "resources": collect_resources(source_project),
        "meta": {"source_project": str(source_project)},
    }


def copy_project(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def inject_before_body_end(html: str, snippet: str) -> str:
    if "</body>" in html.lower():
        return re.sub(r"</body>", snippet + "\n</body>", html, count=1, flags=re.I)
    return html + snippet


def make_edit_dst(src_project: Path, dst_project: Path, idx: int) -> list[dict[str, str]]:
    copy_project(src_project, dst_project)
    index = dst_project / "index.html"
    html = index.read_text(encoding="utf-8", errors="ignore")
    block_id = f"webcode2m-edit-{idx}"
    snippet = f"""
<section id="{block_id}" class="webcode2m-enhancement" aria-labelledby="{block_id}-title">
  <div class="webcode2m-enhancement-inner">
    <p class="webcode2m-kicker">Featured update</p>
    <h2 id="{block_id}-title">Stay connected with the latest updates</h2>
    <p>This new section keeps visitors oriented with a concise summary, useful actions, and a layout that adapts cleanly across screen sizes.</p>
    <form class="webcode2m-signup" aria-label="Email updates signup">
      <input type="email" placeholder="Email address" aria-label="Email address"/>
      <button type="button">Notify me</button>
    </form>
  </div>
</section>
<style>
.webcode2m-enhancement{{margin:48px auto;padding:32px 20px;background:#f4f7fb;border-top:1px solid #d8e0ea;border-bottom:1px solid #d8e0ea}}
.webcode2m-enhancement-inner{{max-width:980px;margin:0 auto;display:grid;gap:14px}}
.webcode2m-kicker{{margin:0;color:#4d6f91;text-transform:uppercase;font-size:13px;font-weight:700;letter-spacing:.08em}}
.webcode2m-enhancement h2{{margin:0;font-size:clamp(24px,4vw,38px);line-height:1.15;color:#1f2f3d}}
.webcode2m-enhancement p{{margin:0;max-width:720px;color:#40515f;line-height:1.6}}
.webcode2m-signup{{display:flex;gap:10px;flex-wrap:wrap;margin-top:8px}}
.webcode2m-signup input{{min-height:44px;min-width:240px;flex:1;border:1px solid #b9c7d3;border-radius:6px;padding:0 12px;font:inherit}}
.webcode2m-signup button{{min-height:44px;border:0;border-radius:6px;background:#1f6feb;color:white;padding:0 18px;font-weight:700;cursor:pointer}}
.webcode2m-signup button:focus-visible,.webcode2m-signup input:focus-visible{{outline:3px solid #80bfff;outline-offset:2px}}
</style>
"""
    new_html = inject_before_body_end(html, snippet)
    index.write_text(new_html, encoding="utf-8")
    return [{"path": "index.html", "search": html, "replace": new_html}]


def make_broken_src(clean_project: Path, broken_project: Path, idx: int) -> list[dict[str, str]]:
    copy_project(clean_project, broken_project)
    index = broken_project / "index.html"
    html = index.read_text(encoding="utf-8", errors="ignore")
    bug_css = f"""
<style id="webcode2m-bug-{idx}">
img{{width:100%!important;height:42px!important;object-fit:fill!important}}
body{{letter-spacing:-1px!important}}
main, section, div{{max-width:280px!important}}
a:focus,button:focus,input:focus{{outline:none!important}}
</style>
"""
    new_html = inject_before_body_end(html, bug_css)
    index.write_text(new_html, encoding="utf-8")
    return [{"path": "index.html", "search": html, "replace": new_html}]


def simple_video(project_dir: Path, out_dir: Path) -> list[dict[str, str]]:
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    html = project_dir / "index.html"
    video_path = out_dir / "index.webm"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=str(out_dir),
            record_video_size={"width": 1280, "height": 720},
        )
        page = context.new_page()
        page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(("file://", "data:", "blob:")) else route.abort())
        page.goto("file://" + str(html.resolve()), wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(800)
        height = page.evaluate("() => document.documentElement.scrollHeight")
        for y in (360, 720, 1080, 1440, max(0, int(height) - 720)):
            page.evaluate("(y) => window.scrollTo({top: y, behavior: 'smooth'})", y)
            page.wait_for_timeout(650)
        raw = Path(page.video.path())
        context.close()
        browser.close()
        if video_path.exists():
            video_path.unlink()
        shutil.move(str(raw), video_path)
    return [{"page": "index.html", "path": video_path.relative_to(out_dir.parent).as_posix()}]


def write_generation(task: str, project: Path, out_root: Path, idx: int) -> None:
    instance_id = f"{project.name}_{task}"
    instance = out_root / task / instance_id
    if instance.exists():
        shutil.rmtree(instance)
    instance.mkdir(parents=True, exist_ok=True)
    copy_project(project, instance / "dst")
    info = case_info(instance_id, task, project)
    info["dst_code"] = read_code_bundle(project)
    if task == "text-generation":
        info["instruction"] = build_instruction(project)
    elif task == "image-generation":
        info["input_screenshots"] = screenshot_project_to_dir(project, instance / "input_screenshots")
        info["instruction"] = "Recreate the website shown in the provided responsive screenshots as an offline-renderable web project."
    elif task == "video-generation":
        info["input_videos"] = simple_video(project, instance / "input_videos")
        info["instruction"] = "Recreate the website shown in the provided browsing video, including the visible layout, scroll behavior, and responsive structure."
    safe_write_json(instance / "info.json", info)


def write_edit_pair(task: str, project: Path, out_root: Path, idx: int) -> None:
    instance_id = f"{project.name}_{task}"
    instance = out_root / task / "sp" / instance_id
    if instance.exists():
        shutil.rmtree(instance)
    instance.mkdir(parents=True, exist_ok=True)
    copy_project(project, instance / "src")
    patches = make_edit_dst(project, instance / "dst", idx)
    info = case_info(instance_id, task, project)
    info["task_family"] = "edit"
    info["task_type"] = ["Content Section", "Form Enhancement", "Responsive Layout"]
    info["description"] = [{"task_type": "Content Section", "description": EDIT_DESCRIPTIONS[idx % len(EDIT_DESCRIPTIONS)]}]
    info["instruction"] = EDIT_DESCRIPTIONS[idx % len(EDIT_DESCRIPTIONS)]
    info["src_code"] = read_code_bundle(instance / "src")
    info["dst_code"] = read_code_bundle(instance / "dst")
    info["label_modified_files"] = patches
    if task == "image-editing":
        info["src_screenshot"] = screenshot_project_to_dir(instance / "src", instance / "src_screenshots")
        info["dst_screenshot"] = screenshot_project_to_dir(instance / "dst", instance / "dst_screenshots")
    safe_write_json(instance / "info.json", info)


def write_repair_pair(task: str, project: Path, out_root: Path, idx: int) -> None:
    instance_id = f"{project.name}_{task}"
    instance = out_root / task / "sp" / instance_id
    if instance.exists():
        shutil.rmtree(instance)
    instance.mkdir(parents=True, exist_ok=True)
    patches = make_broken_src(project, instance / "src", idx)
    copy_project(project, instance / "dst")
    info = case_info(instance_id, task, project)
    info["task_family"] = "repair"
    info["task_type"] = ["Sizing Proportion", "Overflow", "Accessibility"]
    info["description"] = [{"task_type": "Sizing Proportion", "description": REPAIR_DESCRIPTIONS[idx % len(REPAIR_DESCRIPTIONS)]}]
    info["instruction"] = REPAIR_DESCRIPTIONS[idx % len(REPAIR_DESCRIPTIONS)]
    info["src_code"] = read_code_bundle(instance / "src")
    info["dst_code"] = read_code_bundle(instance / "dst")
    info["label_modified_files"] = patches
    if task == "image-repair":
        info["src_screenshot"] = screenshot_project_to_dir(instance / "src", instance / "src_screenshots")
        info["dst_screenshot"] = screenshot_project_to_dir(instance / "dst", instance / "dst_screenshots")
    safe_write_json(instance / "info.json", info)


def choose_projects(input_dir: Path, limit: int) -> list[Path]:
    projects = sorted((input_dir / "projects").iterdir())
    scored = []
    for p in projects:
        meta_path = p / "metadata.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        stats = meta.get("stats", {})
        penalty = stats.get("fallback_asset", 0) + stats.get("root_relative_fallback", 0) + stats.get("relative_fallback", 0)
        bonus = stats.get("downloaded", 0)
        lang_bonus = 5 if meta.get("lang") in {"en", "zh"} else 0
        scored.append((penalty - bonus - lang_bonus, p))
    return [p for _, p in sorted(scored)[:limit]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=Path("WebCoding_Data/local_trials/webcode2m_clean_100"))
    parser.add_argument("--output-dir", type=Path, default=Path("WebCoding_Data/local_trials/webcode2m_cases_7x10"))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.output_dir.exists() and args.overwrite:
        shutil.rmtree(args.output_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    projects = choose_projects(args.input_dir, args.limit)
    manifest = []
    for idx, project in enumerate(projects):
        for task in TASKS:
            try:
                if task in {"text-generation", "image-generation", "video-generation"}:
                    write_generation(task, project, args.output_dir, idx)
                elif task in {"text-editing", "image-editing"}:
                    write_edit_pair(task, project, args.output_dir, idx)
                else:
                    write_repair_pair(task, project, args.output_dir, idx)
                manifest.append({"project": project.name, "task": task, "status": "ok"})
                print(json.dumps(manifest[-1], ensure_ascii=False), flush=True)
            except Exception as exc:  # noqa: BLE001
                manifest.append({"project": project.name, "task": task, "status": "error", "error": f"{type(exc).__name__}: {exc}"})
                print(json.dumps(manifest[-1], ensure_ascii=False), flush=True)
    safe_write_json(args.output_dir / "manifest.json", {"items": manifest})


if __name__ == "__main__":
    main()
