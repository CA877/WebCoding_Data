from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from playwright.sync_api import Page, sync_playwright


VIEWPORT = {"width": 1280, "height": 720}
VIDEO_SIZE = {"width": 1280, "height": 720}


def now_ms(start: float) -> int:
    return int((time.time() - start) * 1000)


def safe_name(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)
    return cleaned.strip("_") or "page"


def visible_box(page: Page, selector: str, index: int = 0) -> Optional[Dict[str, float]]:
    locator = page.locator(selector).nth(index)
    try:
        if not locator.is_visible(timeout=700):
            return None
        box = locator.bounding_box(timeout=700)
    except Exception:
        return None
    if not box or box["width"] < 4 or box["height"] < 4:
        return None
    return box


def locator_text(page: Page, selector: str, index: int = 0) -> str:
    locator = page.locator(selector).nth(index)
    try:
        text = locator.inner_text(timeout=500).strip()
    except Exception:
        text = ""
    if text:
        return " ".join(text.split())[:80]
    try:
        return str(locator.get_attribute("aria-label", timeout=500) or "").strip()[:80]
    except Exception:
        return ""


class HumanRecorder:
    def __init__(self, page: Page, out_dir: Path, start: float) -> None:
        self.page = page
        self.out_dir = out_dir
        self.frames_dir = out_dir / "keyframes"
        self.frames_dir.mkdir(parents=True, exist_ok=True)
        self.start = start
        self.actions: List[Dict[str, Any]] = []
        self.mouse_x = 80.0
        self.mouse_y = 80.0
        self.frame_no = 0

    def log(self, action: str, **extra: Any) -> None:
        self.actions.append({"t_ms": now_ms(self.start), "action": action, **extra})

    def pause(self, low: int = 350, high: int = 900, reason: str = "pause") -> None:
        delay = random.randint(low, high)
        self.log(reason, duration_ms=delay)
        self.page.wait_for_timeout(delay)

    def install_cursor(self) -> None:
        self.page.add_style_tag(
            content="""
            #__human_cursor {
              position: fixed;
              left: 0;
              top: 0;
              width: 18px;
              height: 18px;
              border: 2px solid #111827;
              background: rgba(255,255,255,.72);
              border-radius: 50%;
              box-shadow: 0 2px 10px rgba(15,23,42,.28);
              transform: translate(-50%, -50%);
              z-index: 2147483647;
              pointer-events: none;
              transition: width .12s ease, height .12s ease, background .12s ease;
            }
            #__human_cursor::after {
              content: "";
              position: absolute;
              left: 50%;
              top: 50%;
              width: 4px;
              height: 4px;
              border-radius: 50%;
              background: #111827;
              transform: translate(-50%, -50%);
            }
            #__human_cursor.__clicking {
              width: 28px;
              height: 28px;
              background: rgba(250,204,21,.45);
            }
            """
        )
        self.page.evaluate(
            """([x, y]) => {
                const old = document.getElementById("__human_cursor");
                if (old) old.remove();
                const cursor = document.createElement("div");
                cursor.id = "__human_cursor";
                cursor.style.left = `${x}px`;
                cursor.style.top = `${y}px`;
                document.body.appendChild(cursor);
            }""",
            [self.mouse_x, self.mouse_y],
        )
        self.page.mouse.move(self.mouse_x, self.mouse_y)

    def set_cursor(self, x: float, y: float) -> None:
        self.page.evaluate(
            """([x, y]) => {
                const cursor = document.getElementById("__human_cursor");
                if (cursor) {
                  cursor.style.left = `${x}px`;
                  cursor.style.top = `${y}px`;
                }
            }""",
            [x, y],
        )

    def move_to(self, x: float, y: float, label: str = "move") -> None:
        steps = max(8, min(28, int(math.hypot(x - self.mouse_x, y - self.mouse_y) / 35)))
        for i in range(1, steps + 1):
            t = i / steps
            ease = 0.5 - math.cos(t * math.pi) / 2
            wobble = math.sin(t * math.pi * 2) * random.uniform(-2.0, 2.0)
            nx = self.mouse_x + (x - self.mouse_x) * ease + wobble
            ny = self.mouse_y + (y - self.mouse_y) * ease + wobble
            self.page.mouse.move(nx, ny)
            self.set_cursor(nx, ny)
            self.page.wait_for_timeout(random.randint(18, 34))
        self.mouse_x, self.mouse_y = x, y
        self.log(label, x=round(x, 1), y=round(y, 1))

    def move_to_box(self, box: Dict[str, float], label: str = "move") -> Tuple[float, float]:
        x = box["x"] + min(max(box["width"] * random.uniform(0.35, 0.65), 6), box["width"] - 3)
        y = box["y"] + min(max(box["height"] * random.uniform(0.35, 0.65), 6), box["height"] - 3)
        self.move_to(x, y, label)
        return x, y

    def click_at_cursor(self, label: str, text: str = "") -> None:
        self.page.evaluate(
            """() => {
                const cursor = document.getElementById("__human_cursor");
                if (cursor) cursor.classList.add("__clicking");
            }"""
        )
        self.page.mouse.down()
        self.page.wait_for_timeout(random.randint(70, 130))
        self.page.mouse.up()
        self.page.evaluate(
            """() => {
                const cursor = document.getElementById("__human_cursor");
                if (cursor) cursor.classList.remove("__clicking");
            }"""
        )
        self.log(label, text=text, x=round(self.mouse_x, 1), y=round(self.mouse_y, 1))
        self.pause(450, 950, "after_click_wait")

    def keyframe(self, name: str) -> None:
        self.frame_no += 1
        path = self.frames_dir / f"{self.frame_no:02d}_{safe_name(name)}.jpg"
        self.page.screenshot(path=str(path), type="jpeg", quality=82, full_page=False)
        self.log("keyframe", name=name, path=str(path.relative_to(self.out_dir)))

    def hover_selector(self, selector: str, index: int = 0, name: str = "hover") -> bool:
        box = visible_box(self.page, selector, index)
        if not box:
            return False
        text = locator_text(self.page, selector, index)
        self.move_to_box(box, f"hover_{name}")
        self.pause(500, 1200, "hover_read")
        self.keyframe(f"hover_{name}_{index}")
        self.log("hover_target", selector=selector, index=index, text=text)
        return True

    def click_selector(self, selector: str, index: int = 0, name: str = "target") -> bool:
        box = visible_box(self.page, selector, index)
        if not box:
            return False
        text = locator_text(self.page, selector, index)
        self.move_to_box(box, f"approach_{name}")
        self.pause(250, 700, "pre_click_read")
        self.click_at_cursor(f"click_{name}", text=text)
        self.keyframe(f"after_click_{name}_{index}")
        return True

    def wheel(self, delta_y: int, label: str) -> None:
        ticks = max(1, abs(delta_y) // 220)
        for _ in range(ticks):
            part = int(delta_y / ticks) + random.randint(-24, 24)
            self.page.mouse.wheel(0, part)
            self.log(label, delta_y=part)
            self.page.wait_for_timeout(random.randint(180, 390))


def candidate_indices(page: Page, selector: str, max_count: int = 8) -> Iterable[int]:
    try:
        count = min(page.locator(selector).count(), max_count)
    except Exception:
        count = 0
    return range(count)


def run_story(page: Page, recorder: HumanRecorder) -> None:
    recorder.install_cursor()
    recorder.pause(900, 1400, "initial_read")
    recorder.keyframe("initial")

    # Read the page like a person: hover header controls and nearby controls first.
    for selector, name in [
        ("header button, [role=banner] button", "header_button"),
        ("nav a, header a", "nav_link"),
        ("main button, aside button, .btn, [role=button]", "primary_button"),
    ]:
        for idx in candidate_indices(page, selector, 3):
            recorder.hover_selector(selector, idx, name)
            break

    # Prefer semantic paths over exhausting one widget family. For filter UIs, show
    # both the preset controls and the checkbox controls so the video explains why
    # those components exist.
    clicked_semantic_control = False
    if page.locator(".quick-select__btn").count():
        for idx in [1, 3]:
            if recorder.click_selector(".quick-select__btn", idx, "quick_select"):
                clicked_semantic_control = True

    if page.locator("label:has(input[type=checkbox])").count():
        clicked = 0
        for idx in range(min(page.locator("label:has(input[type=checkbox])").count(), 8)):
            text = locator_text(page, "label:has(input[type=checkbox])", idx)
            # After the $150+ preset in the beauty sample, the nonzero choices are
            # Tom Ford and La Mer; in other pages this still clicks the first
            # visible checkbox labels if no counts/text match.
            if clicked < 2 and (not clicked_semantic_control or any(token in text for token in ["Tom Ford", "La Mer"])):
                if recorder.click_selector("label:has(input[type=checkbox])", idx, "checkbox_label"):
                    clicked += 1
                    clicked_semantic_control = True
        if clicked == 0:
            for idx in candidate_indices(page, "label:has(input[type=checkbox])", 3):
                if recorder.click_selector("label:has(input[type=checkbox])", idx, "checkbox_label"):
                    clicked_semantic_control = True
                    break

    if not clicked_semantic_control:
        priority_clicks = [
            ("[role=tab]", "tab"),
            ("details summary", "details"),
            ("button[aria-expanded]", "expand_button"),
            ("button:has-text('Filter'), button:has-text('Menu'), button:has-text('Options')", "menu_button"),
            ("button:not([disabled])", "button"),
        ]
        used = 0
        for selector, name in priority_clicks:
            for idx in candidate_indices(page, selector, 4):
                if recorder.click_selector(selector, idx, name):
                    used += 1
                    if used >= 3:
                        break
            if used >= 3:
                break

    # Focus/type into text-like fields if present.
    for selector in ["input[type=search]", "input[type=text]", "textarea"]:
        for idx in candidate_indices(page, selector, 2):
            box = visible_box(page, selector, idx)
            if not box:
                continue
            recorder.move_to_box(box, "approach_input")
            recorder.click_at_cursor("focus_input", text=locator_text(page, selector, idx))
            try:
                page.keyboard.type("serum", delay=random.randint(45, 90))
                recorder.log("type_text", value="serum")
                recorder.pause(500, 1000, "after_type_wait")
                recorder.keyframe("after_type")
                break
            except Exception:
                pass
        else:
            continue
        break

    # Use real wheel gestures with uneven pauses instead of jump scrolling.
    for i, delta in enumerate([420, 560, 360, -240, 620, 740], 1):
        recorder.wheel(delta, f"wheel_scroll_{i}")
        if i in {2, 4, 6}:
            recorder.pause(650, 1400, "section_read")
            recorder.keyframe(f"scroll_position_{i}")

    # Product/card hover near the end makes layout state visible.
    for selector in [".card", ".product-card", "article", "[role=listitem]"]:
        for idx in candidate_indices(page, selector, 4):
            if recorder.hover_selector(selector, idx, "content_card"):
                return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    random.seed(args.seed)
    out_dir = Path(args.output_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    video_dir = out_dir / "video_raw"
    video_dir.mkdir(parents=True, exist_ok=True)

    start = time.time()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(video_dir),
            record_video_size=VIDEO_SIZE,
        )
        page = context.new_page()

        if args.local_only:
            def route_local(route):
                url = route.request.url
                if url.startswith(("file://", "data:", "blob:")):
                    route.continue_()
                else:
                    route.abort("connectionfailed")

            page.route("**/*", route_local)

        page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(1500)

        recorder = HumanRecorder(page, out_dir, start)
        run_story(page, recorder)
        recorder.pause(800, 1200, "final_pause")

        video = page.video
        context.close()
        final_video = out_dir / "human_like_recording.webm"
        if video:
            raw_path = Path(video.path())
            if raw_path.exists():
                shutil.move(str(raw_path), final_video)
        browser.close()

    (out_dir / "actions.json").write_text(
        json.dumps(recorder.actions, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"output_dir": str(out_dir), "actions": len(recorder.actions)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
