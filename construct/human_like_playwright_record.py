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


# ---------------------------------------------------------------------------
# Page discovery – scan the DOM once to learn what interactive elements exist
# ---------------------------------------------------------------------------

def _page_dimensions(page: Page) -> dict:
    """Return scrollHeight, viewport height, and current scroll position."""
    return page.evaluate("""() => ({
        scroll_height: document.body.scrollHeight || document.documentElement.scrollHeight,
        viewport_height: window.innerHeight,
        scroll_y: window.scrollY,
        viewport_width: window.innerWidth,
    })""")


def _discover_interactive(page: Page) -> dict:
    """One-shot JS scan that returns counts and positions of key interactive elements.

    Returns a flat dict of counts (cheap) plus lists of {selector, text} for the
    elements that *are* worth hovering/clicking later.
    """
    return page.evaluate("""() => {
        const els = (sel) => Array.from(document.querySelectorAll(sel));

        // Helper: first visible text of an element (or its aria-label)
        function label(el) {
            const aria = el.getAttribute('aria-label') || '';
            if (aria.trim()) return aria.trim().slice(0, 60);
            const t = (el.textContent || '').replace(/\\s+/g, ' ').trim();
            return t.slice(0, 60);
        }

        // Helper: is an element currently in or near the viewport?
        function nearViewport(el) {
            const r = el.getBoundingClientRect();
            return r.top < window.innerHeight * 1.2 && r.bottom > -window.innerHeight * 0.3;
        }

        // ---------------------------------------------------------------
        // Collect visible interactive elements by category
        // ---------------------------------------------------------------
        const take = (selector, n) =>
            els(selector).filter(nearViewport).slice(0, n).map(el => ({
                selector: selector,
                text: label(el),
                tag: el.tagName.toLowerCase(),
                ariaExpanded: el.getAttribute('aria-expanded'),
                role: el.getAttribute('role') || '',
            }));

        const buttons = take(
            'button:not([disabled]), [role="button"]:not([aria-disabled="true"]), .btn, [class*="button"]', 20);

        const navLinks = take(
            'nav a[href], header a[href], [role="navigation"] a[href]', 10);

        const tabs = take('[role="tab"]', 8);

        const expandables = take(
            'details summary, [aria-expanded]', 8);

        const formInputs = take(
            'input[type="text"]:not([type="hidden"]), input[type="search"], ' +
            'input[type="email"], textarea, select', 6);

        const checkboxes = take(
            'label:has(input[type="checkbox"]), label:has(input[type="radio"])', 6);

        // Cookie / consent detection
        let cookieButton = null;
        for (const btn of els('button, a.button, .btn, [role="button"]')) {
            const t = (btn.textContent || '').toLowerCase();
            if (/accept|agree|consent|got it|ok\\b|allow/i.test(t)) {
                const parentText = ((btn.closest('div,section,aside,dialog,[role="dialog"]')||{}).textContent||'');
                if (/cookie|privacy|gdpr|consent/i.test(parentText)) {
                    cookieButton = {selector: 'button', text: (btn.textContent||'').trim().slice(0, 60)};
                    break;
                }
            }
        }

        return {
            scroll_height: document.body.scrollHeight || document.documentElement.scrollHeight,
            viewport_height: window.innerHeight,
            nav_links: navLinks,
            buttons: buttons,
            tabs: tabs,
            expandables: expandables,
            form_inputs: formInputs,
            checkboxes: checkboxes,
            cookie_button: cookieButton,
            total_buttons: els('button, [role="button"]').length,
            total_nav: els('nav a, header a, [role="navigation"] a').length,
            total_forms: els('form').length,
            total_inputs: els('input:not([type="hidden"]), textarea, select').length,
        };
    }""")


def _element_box(page: Page, selector: str, index: int = 0) -> Optional[Dict[str, float]]:
    """Convenience wrapper around visible_box; returns None on any failure."""
    try:
        return visible_box(page, selector, index)
    except Exception:
        return None


def _scroll_to(page: Page, recorder: HumanRecorder, target_y: int, label: str = "scroll") -> None:
    """Scroll from current position to *target_y* using smooth wheel gestures."""
    current = page.evaluate("window.scrollY")
    delta = target_y - current
    if abs(delta) < 20:
        return
    # Use a few medium wheel steps so the scroll looks natural
    steps = max(1, abs(delta) // 250)
    step = delta / steps
    for i in range(steps):
        jitter = random.randint(-20, 20)
        recorder.wheel(int(step) + jitter, f"{label}_{i + 1}")


def _try_click_any(page: Page, recorder: HumanRecorder,
                   candidates: list[dict], max_clicks: int = 2) -> int:
    """Try to click up to *max_clicks* items from a discovered candidate list.

    Returns the number of successful clicks.
    """
    clicked = 0
    for item in candidates:
        if clicked >= max_clicks:
            break
        sel = item.get("selector", "")
        if not sel:
            continue
        # Find which index of this selector matches this item's text
        try:
            count = page.locator(sel).count()
        except Exception:
            continue
        for idx in range(min(count, 12)):
            text = locator_text(page, sel, idx)
            if text and text[:20] == item.get("text", "")[:20]:
                if recorder.click_selector(sel, idx, sel.replace('"', '').replace("'", "")[:20]):
                    clicked += 1
                    break
        else:
            # Fallback: try the first visible occurrence
            if recorder.click_selector(sel, 0, sel.replace('"', '').replace("'", "")[:20]):
                clicked += 1
    return clicked


def _try_hover_any(page: Page, recorder: HumanRecorder,
                   candidates: list[dict], max_hover: int = 3) -> int:
    """Like _try_click_any but only hovers."""
    hovered = 0
    for item in candidates:
        if hovered >= max_hover:
            break
        sel = item.get("selector", "")
        if not sel:
            continue
        if recorder.hover_selector(sel, 0, sel.replace('"', '').replace("'", "")[:20]):
            hovered += 1
    return hovered


# ---------------------------------------------------------------------------
# Main story – generic, page-structure-aware human-like interaction
# ---------------------------------------------------------------------------

def run_story(
    page: Page,
    recorder: HumanRecorder,
    *,
    type_text: str = "hello",
    max_scroll_stops: int = 5,
    clicks_per_stop: int = 2,
) -> None:
    """Record a human-like interaction video on *page*.

    The function discovers what interactive elements exist on the page and then
    follows a top-to-bottom traversal, clicking meaningful widgets as it goes.
    Every phase is wrapped in its own try/except so a failure in one part does
    not kill the whole recording.
    """

    # ---- Phase 0: discover the page ----------------------------------------
    dims = _page_dimensions(page)
    info: dict = {}
    try:
        info = _discover_interactive(page)
    except Exception:
        info = {}

    total_h = info.get("scroll_height", dims.get("scroll_height", 2000))
    vp_h = info.get("viewport_height", dims.get("viewport_height", 720))

    # ---- cursor + initial view ---------------------------------------------
    recorder.install_cursor()
    recorder.pause(900, 1400, "initial_read")
    recorder.keyframe("initial")

    # ---- Phase 1: above-the-fold -------------------------------------------
    try:
        _phase1_above_fold(page, recorder, info)
    except Exception:
        pass

    # ---- Phase 2: progressive content walk ---------------------------------
    try:
        _phase2_content_walk(page, recorder, total_h, vp_h,
                             max_scroll_stops, clicks_per_stop)
    except Exception:
        pass

    # ---- Phase 3: form interaction -----------------------------------------
    try:
        _phase3_form_interaction(page, recorder, info, type_text)
    except Exception:
        pass

    # ---- Phase 4: footer & card hover --------------------------------------
    try:
        _phase4_footer(page, recorder, info, total_h)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Phase implementations
# ---------------------------------------------------------------------------

def _phase1_above_fold(page: Page, recorder: HumanRecorder, info: dict) -> None:
    """Interact with header/nav and the most prominent above-the-fold controls."""

    # Hover 2-3 nav links to show navigation awareness
    nav = info.get("nav_links", [])
    if nav:
        _try_hover_any(page, recorder, nav, max_hover=3)

    # Click the most interactive-looking things first: expandables, then tabs,
    # then generic buttons.
    for category, max_n in [("expandables", 2), ("tabs", 2), ("buttons", 2)]:
        items = info.get(category, [])
        if items:
            _try_click_any(page, recorder, items, max_clicks=max_n)

    # If a cookie-consent button was detected, click it once to dismiss
    cookie = info.get("cookie_button")
    if cookie:
        _try_click_any(page, recorder, [cookie], max_clicks=1)


def _phase2_content_walk(
    page: Page, recorder: HumanRecorder,
    total_h: int, vp_h: int,
    max_stops: int, clicks_per_stop: int,
) -> None:
    """Scroll down the page in segments, pausing at each stop to interact."""

    # Compute scroll-stop Y positions: spread across the page height, skipping
    # the very top (already covered) and very bottom (covered by phase 4).
    if total_h <= vp_h * 1.3:
        # Short page – one stop in the middle, then done
        stops = [total_h // 2]
    else:
        content_h = max(0, total_h - vp_h * 0.8)
        step = content_h / min(max_stops, max(1, content_h // (vp_h * 1.2)))
        stops = [int(vp_h * 0.6 + step * i) for i in range(1, min(max_stops + 1, int(content_h // step) + 1))]
        # Clamp to page bounds
        stops = [s for s in stops if s < total_h - 100]

    if not stops:
        return

    for i, target_y in enumerate(stops, 1):
        _scroll_to(page, recorder, target_y, f"scroll_to_stop_{i}")
        recorder.pause(500, 1000, "section_read")
        recorder.keyframe(f"scroll_stop_{i}")

        # Re-discover what's visible now
        try:
            visible = _discover_interactive(page)
        except Exception:
            visible = {}

        # Click meaningful elements in this viewport
        _try_click_any(page, recorder, visible.get("expandables", []),
                       max_clicks=clicks_per_stop)
        _try_click_any(page, recorder, visible.get("tabs", []),
                       max_clicks=clicks_per_stop)
        _try_click_any(page, recorder, visible.get("checkboxes", []),
                       max_clicks=1)
        _try_click_any(page, recorder, visible.get("buttons", []),
                       max_clicks=clicks_per_stop)


def _phase3_form_interaction(page: Page, recorder: HumanRecorder,
                             info: dict, type_text: str) -> None:
    """If there is a visible text-like input, click it and type some text."""

    inputs = info.get("form_inputs", [])
    if not inputs:
        # Fallback: try generic selectors
        for sel in ["input[type=text]", "input[type=search]", "input[type=email]", "textarea"]:
            box = _element_box(page, sel, 0)
            if box:
                inputs = [{"selector": sel, "text": ""}]
                break

    for item in inputs[:1]:  # only interact with one input
        sel = item.get("selector", "")
        if not sel:
            continue
        box = _element_box(page, sel, 0)
        if not box:
            continue
        recorder.move_to_box(box, "approach_input")
        recorder.click_at_cursor("focus_input", text=locator_text(page, sel, 0))
        try:
            page.keyboard.type(type_text, delay=random.randint(45, 90))
            recorder.log("type_text", value=type_text)
            recorder.pause(500, 1000, "after_type_wait")
            recorder.keyframe("after_type")
        except Exception:
            pass
        break


def _phase4_footer(page: Page, recorder: HumanRecorder,
                   info: dict, total_h: int) -> None:
    """Scroll near the bottom and hover remaining content cards / footer links."""

    # Scroll to ~85% of the page so we see footer-area content
    target = max(0, total_h - int(info.get("viewport_height", 720) * 0.85))
    _scroll_to(page, recorder, target, "scroll_to_footer")
    recorder.pause(600, 1200, "footer_read")
    recorder.keyframe("near_bottom")

    # Hover any remaining card-like or article elements
    for sel in ["article", ".card", ".product-card", "[role=listitem]", "footer a"]:
        for idx in candidate_indices(page, sel, 3):
            if recorder.hover_selector(sel, idx, f"bottom_{sel[:20]}"):
                break


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
