#!/usr/bin/env python3
"""Add clean, functional Vanilla JS to existing HTML/CSS projects.

Takes cleaned WebRenderBench or crawled projects (which may lack JS or have broken JS),
analyzes the HTML/CSS structure, and uses an LLM to generate appropriate main.js.

Each project is randomly assigned 4-7 JS features from a catalog of 30+ features
aligned with 4 benchmarks: WebCompass, Vision2Web, Design2Code, FLAME-VLM-Code.

Usage:
    python3 construct/add_js.py \
        --input-dir /data/cleaned_projects/ \
        --output-dir /data/projects_with_js/ \
        --concurrency 5 \
        --limit 10
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from construct_common import (
    copy_project,
    ensure_api_env,
    maybe_load_env,
    read_code_bundle,
)


# ---------------------------------------------------------------------------
# JS Feature Catalog — aligned with WebCompass, Vision2Web, Design2Code, FLAME
# ---------------------------------------------------------------------------
# Each feature has a detailed implementation guide so the LLM produces
# consistent, high-quality code regardless of the model used.
#
# category="enhance": needs existing HTML elements, skip if not found
# category="inject": creates new DOM elements via JS, works on any page

JS_FEATURE_CATALOG = {

    # ===== A类: Enhance existing HTML elements =====

    "mobile_menu": {
        "category": "enhance",
        "name": "Mobile Hamburger Menu",
        "desc": (
            "Detect the main navigation element (nav, .nav, .menu, or header ul). "
            "Create a hamburger button (☰ / ✕ toggle) that is visible only when "
            "viewport width < 768px (check via window.matchMedia or resize listener). "
            "On click, toggle the nav's visibility with a CSS class (.nav-open) that "
            "slides/fades the menu in. Add aria-expanded attribute for accessibility. "
            "Close the menu when a link inside it is clicked."
        ),
    },
    "dropdown_menu": {
        "category": "enhance",
        "name": "Dropdown Sub-menus",
        "desc": (
            "Find navigation items that contain nested <ul> sub-lists. "
            "On hover (desktop) or click (mobile), show the sub-list with a "
            "slide-down or fade-in transition. Add a small arrow indicator (▼) "
            "via JS. Close other open dropdowns when a new one opens. "
            "Close all dropdowns when clicking outside the nav."
        ),
    },
    "sticky_header": {
        "category": "enhance",
        "name": "Sticky Header on Scroll",
        "desc": (
            "Detect the page header or first nav element. "
            "On scroll past 80px, add a .sticky class that sets position:fixed, "
            "top:0, width:100%, z-index:9999, and a subtle box-shadow. "
            "Add a smooth transition. Remove the class when scrolled back to top. "
            "Optionally add a hide-on-scroll-down, show-on-scroll-up behavior."
        ),
    },
    "smooth_scroll": {
        "category": "enhance",
        "name": "Smooth Scroll for Anchor Links",
        "desc": (
            "Find all <a href='#...'>  links with a hash target. "
            "On click, prevent default and use element.scrollIntoView({behavior:'smooth'}). "
            "Offset by header height if a sticky header exists. "
            "Update the URL hash without jumping."
        ),
    },
    "active_nav_highlight": {
        "category": "enhance",
        "name": "Active Navigation Link Highlighting",
        "desc": (
            "On scroll, detect which section is currently in the viewport "
            "using IntersectionObserver or scroll position calculation. "
            "Add an .active class to the corresponding nav link. "
            "Remove .active from all other links. "
            "Style the active link with a border-bottom or background change."
        ),
    },
    "tabs": {
        "category": "enhance",
        "name": "Tab Switching Component",
        "desc": (
            "Find elements that resemble tabs (.tab, [role='tab'], .tab-button, "
            "or a group of buttons/links followed by content panels). "
            "On click, show the corresponding content panel and hide others. "
            "Add .active class to the selected tab button. "
            "Set aria-selected and aria-hidden attributes. "
            "Support keyboard navigation (Left/Right arrow keys)."
        ),
    },
    "accordion": {
        "category": "enhance",
        "name": "Accordion / Collapsible Panels",
        "desc": (
            "Find groups of heading+content pairs (h2+div, h3+p, dt+dd, "
            ".accordion-header+.accordion-content, or similar patterns). "
            "Add click handlers to headings that toggle the next sibling's visibility "
            "with a max-height CSS transition. Add a rotation indicator (▶ → ▼). "
            "Optionally allow only one panel open at a time. "
            "Set aria-expanded on the header."
        ),
    },
    "carousel": {
        "category": "enhance",
        "name": "Image/Card Carousel Slider",
        "desc": (
            "Find groups of same-type sibling elements (cards, images, slides). "
            "Show one or a few at a time. Create Previous/Next arrow buttons "
            "and dot indicators. Use CSS transform:translateX for sliding animation. "
            "Support auto-play with setInterval (pause on hover). "
            "Support touch/swipe via touchstart/touchend events. "
            "Loop back to first slide after last."
        ),
    },
    "form_validation": {
        "category": "enhance",
        "name": "Form Validation with Feedback",
        "desc": (
            "Find all <form> elements and their inputs. For each input, "
            "validate on blur and on form submit: "
            "- Required fields: show 'This field is required' if empty. "
            "- Email fields: validate with regex pattern. "
            "- Min-length: check password/text length. "
            "Show inline error messages (red text below input). "
            "Add red border to invalid inputs, green to valid ones. "
            "Prevent form submission if any validation fails. "
            "Add a shake animation on the form when submit fails. "
            "Clear errors on focus."
        ),
    },
    "char_counter": {
        "category": "enhance",
        "name": "Character Counter for Textareas",
        "desc": (
            "Find all <textarea> elements. Below each, add a character count "
            "display showing 'N / MAX characters'. Set a reasonable max (500). "
            "Update the count on each input event. "
            "Change color to orange when 80% full, red when 100%. "
            "Prevent typing beyond the max."
        ),
    },
    "password_toggle": {
        "category": "enhance",
        "name": "Show/Hide Password Toggle",
        "desc": (
            "Find all input[type='password'] fields. "
            "Add an eye icon button (👁 / 👁‍🗨) next to each one. "
            "On click, toggle the input type between 'password' and 'text'. "
            "Toggle the icon between open/closed eye."
        ),
    },
    "lightbox": {
        "category": "enhance",
        "name": "Image Lightbox / Gallery Modal",
        "desc": (
            "Find all content images (not icons/logos — check size or context). "
            "On click, open a full-screen overlay with the image displayed large. "
            "Add left/right arrows to navigate between images. "
            "Add a close button (✕) and close on backdrop click or Escape key. "
            "Show the current image number (3 / 12). "
            "Prevent body scroll while lightbox is open."
        ),
    },
    "search_filter": {
        "category": "enhance",
        "name": "Live Search / Filter for Lists",
        "desc": (
            "Find the main content list (ul, ol, .cards, table tbody, "
            "or a set of repeated sibling elements). "
            "Create a search input field above it. "
            "On keyup (debounced 200ms), filter items: hide those whose "
            "text content doesn't match the query (case-insensitive). "
            "Show a 'No results found' message when nothing matches. "
            "Show the count of visible items."
        ),
    },
    "table_sort": {
        "category": "enhance",
        "name": "Sortable Table Columns",
        "desc": (
            "Find <table> elements with <th> headers. "
            "Make each th clickable. On click, sort the table rows by that column. "
            "Toggle between ascending and descending. "
            "Add a sort indicator arrow (▲/▼) to the active column. "
            "Support both alphabetical and numeric sorting (auto-detect). "
            "Maintain zebra striping after sort."
        ),
    },
    "read_more": {
        "category": "enhance",
        "name": "Read More / Text Truncation",
        "desc": (
            "Find long text paragraphs (>200 characters). "
            "Truncate to 3 lines or 150 characters with a '... Read more' link. "
            "On click, expand to show full text with 'Read less' link. "
            "Use max-height + overflow:hidden with CSS transition for smooth animation."
        ),
    },

    # ===== B类: Inject new UI components (works on any page) =====

    "theme_toggle": {
        "category": "inject",
        "name": "Dark / Light Theme Toggle",
        "desc": (
            "Create a floating theme toggle button (☀️/🌙 or text 'Dark'/'Light') "
            "in the top-right corner or inside the header. "
            "On click, add/remove a .dark-theme class on <body>. "
            "In dark mode: set background to #1a1a2e, text to #e0e0e0, "
            "cards/sections to #16213e, links to #4fc3f7. "
            "Apply the styles by injecting a <style> block via JS. "
            "Save preference to localStorage('theme'). "
            "On page load, read localStorage and apply the saved theme. "
            "Add a smooth 0.3s transition on background-color and color."
        ),
    },
    "back_to_top": {
        "category": "inject",
        "name": "Back to Top Button",
        "desc": (
            "Create a circular button (▲ or ↑) fixed at bottom-right corner. "
            "Hidden by default; show with fade-in when scrolled past 300px. "
            "On click, smoothly scroll to top. "
            "Style: 50px circle, semi-transparent background, z-index:99999."
        ),
    },
    "scroll_progress": {
        "category": "inject",
        "name": "Scroll Progress Indicator",
        "desc": (
            "Create a thin (3-4px) colored bar fixed at the very top of the viewport "
            "(above everything, z-index:999999). "
            "Width = percentage of page scrolled (0% at top, 100% at bottom). "
            "Use a gradient or solid accent color. "
            "Update on scroll with requestAnimationFrame for smoothness."
        ),
    },
    "toast_system": {
        "category": "inject",
        "name": "Toast Notification System",
        "desc": (
            "Create a toast container fixed at top-right corner. "
            "Implement a showToast(message, type) function where type is "
            "'success' (green), 'error' (red), 'warning' (orange), 'info' (blue). "
            "Each toast slides in from right, shows for 4 seconds, then fades out. "
            "Stack multiple toasts vertically. "
            "Add a close button (✕) on each toast. "
            "Demo: show a 'Welcome!' info toast on page load after 1 second. "
            "Show a 'Settings saved' success toast after 3 seconds."
        ),
    },
    "modal_system": {
        "category": "inject",
        "name": "Modal / Dialog System",
        "desc": (
            "Implement a reusable modal system: "
            "createModal(title, bodyHTML, options) function. "
            "Modal has a dark backdrop (rgba(0,0,0,0.5)), centered white card, "
            "title bar, body content area, and footer with action buttons. "
            "Close on backdrop click, Escape key, or ✕ button. "
            "Add open/close animations (scale + fade). "
            "Prevent body scroll while modal is open. "
            "Demo: add a clickable 'About' or 'Info' link somewhere visible that opens "
            "a modal with site information."
        ),
    },
    "cookie_banner": {
        "category": "inject",
        "name": "Cookie Consent Banner",
        "desc": (
            "Create a fixed-bottom banner with text 'This website uses cookies...' "
            "and two buttons: 'Accept All' and 'Preferences'. "
            "On 'Accept All': save consent to localStorage, hide banner with slide-down. "
            "On 'Preferences': show a modal with checkboxes for 'Essential' (disabled, always on), "
            "'Analytics', 'Marketing'. Save selections to localStorage. "
            "Don't show the banner if consent was already given (check localStorage on load)."
        ),
    },
    "notification_center": {
        "category": "inject",
        "name": "Notification Center with Bell Icon",
        "desc": (
            "Create a bell icon (🔔) in the header or top-right corner with a "
            "red badge showing unread count. "
            "On click, toggle a dropdown panel listing notifications. "
            "Each notification has: icon, title, description, timestamp, and unread dot. "
            "Support 'Mark as read' (click) and 'Mark all as read' button. "
            "Notification types: info (blue), success (green), warning (orange). "
            "Pre-populate with 3-5 sample notifications. "
            "Simulate a new notification arriving every 15 seconds via setInterval."
        ),
    },
    "scroll_animations": {
        "category": "inject",
        "name": "Scroll-triggered Entrance Animations",
        "desc": (
            "Use IntersectionObserver to detect when elements enter the viewport. "
            "Add a .reveal class with animation when visible. "
            "Target major sections, cards, images, and headings. "
            "Animation types (alternate between them): "
            "- fade-in (opacity 0→1) "
            "- slide-up (translateY(30px)→0 + fade) "
            "- slide-left (translateX(-30px)→0 + fade) "
            "- scale-in (scale(0.9)→1 + fade). "
            "Use threshold:0.15 so animation triggers when 15% visible. "
            "Only animate once (unobserve after triggering). "
            "Add stagger delay for items in a grid (each +100ms)."
        ),
    },
    "typewriter": {
        "category": "inject",
        "name": "Typewriter Text Effect",
        "desc": (
            "Find the first large heading (h1, or hero title). "
            "Store its original text, then clear it. "
            "Type out the text character by character with a blinking cursor (|). "
            "Speed: ~50ms per character. "
            "After finishing, hold for 2s, then optionally erase and type a second phrase. "
            "Implement with requestAnimationFrame or setInterval. "
            "The cursor should blink (0.7s interval) while idle."
        ),
    },
    "parallax": {
        "category": "inject",
        "name": "Parallax Scrolling Effect",
        "desc": (
            "Apply parallax effect to hero sections or large background areas. "
            "On scroll, translate background images or section backgrounds at "
            "0.3-0.5x the scroll speed (transform: translate3d for GPU acceleration). "
            "Apply subtle parallax to floating decorative elements if they exist. "
            "Reduce/disable on mobile (prefers-reduced-motion or viewport check). "
            "Use requestAnimationFrame for smooth performance."
        ),
    },
    "skeleton_loading": {
        "category": "inject",
        "name": "Skeleton Loading Screen",
        "desc": (
            "On page load, overlay the main content area with skeleton placeholders "
            "that mimic the page layout (rectangular grey blocks with shimmer animation). "
            "Create skeleton shapes for: header bar, hero image, text lines, card grid. "
            "The shimmer uses a CSS linear-gradient animation sweeping left-to-right. "
            "After 1.5-2 seconds, fade out the skeleton and reveal the real content. "
            "Add aria-busy='true' during loading, remove after."
        ),
    },
    "infinite_scroll": {
        "category": "inject",
        "name": "Infinite Scroll with Loading",
        "desc": (
            "Find the main content list or grid. Clone existing items as templates. "
            "Use IntersectionObserver on a sentinel element at the bottom. "
            "When visible: show a spinner, wait 800ms (simulate fetch), "
            "then append 4-6 cloned items with new numbering. "
            "After 3 batches, show 'No more items to load' message. "
            "Add a loading spinner (CSS-only spinning circle)."
        ),
    },
    "view_toggle": {
        "category": "inject",
        "name": "Grid / List View Toggle",
        "desc": (
            "Find the main content container with repeated items (cards, articles, products). "
            "Create a toggle bar with two buttons: Grid (▦) and List (☰). "
            "Grid view: items in a CSS grid (3 columns on desktop, 2 tablet, 1 mobile). "
            "List view: items stacked vertically, each as a horizontal row. "
            "Save preference to localStorage. "
            "Add smooth transition when switching views. "
            "Highlight the active view button."
        ),
    },
    "keyboard_shortcuts": {
        "category": "inject",
        "name": "Keyboard Shortcuts",
        "desc": (
            "Add global keyboard shortcuts: "
            "- '/' or Ctrl+K: focus a search input (create one if not exists). "
            "- Escape: close any open modal/dropdown/menu. "
            "- 't': toggle theme (if theme_toggle exists). "
            "- '?' or Shift+/: show a shortcuts help modal listing all shortcuts. "
            "Show a brief toast hint ('Press ? for shortcuts') on first page load "
            "(use localStorage to show only once)."
        ),
    },
    "context_menu": {
        "category": "inject",
        "name": "Custom Right-click Context Menu",
        "desc": (
            "Override the default right-click menu on the main content area. "
            "Show a custom menu with options: Copy Link, Share, Print, View Source. "
            "Position the menu at cursor coordinates. "
            "Close on click outside, Escape, or clicking an option. "
            "Add hover highlight on menu items. "
            "Each option shows a toast message on click."
        ),
    },
    "drag_reorder": {
        "category": "inject",
        "name": "Drag & Drop Reorder",
        "desc": (
            "Find a list or grid of items. Make them draggable (draggable='true'). "
            "On dragstart: add a .dragging class (opacity:0.4), store the item. "
            "On dragover: determine insertion point, show a placeholder line. "
            "On drop: move the item to the new position in the DOM. "
            "Add grab cursor on hover. "
            "Save the new order to localStorage. "
            "Restore order from localStorage on page load."
        ),
    },
    "shopping_cart": {
        "category": "inject",
        "name": "Shopping Cart Widget",
        "desc": (
            "Add 'Add to Cart' buttons to product-like items (cards, images with prices, etc.). "
            "Create a cart icon (🛒) in the header with a badge showing item count. "
            "On click, open a slide-in sidebar panel showing cart items with: "
            "- Thumbnail, name, quantity +/- controls, remove button. "
            "- Subtotal per item and grand total at bottom. "
            "- 'Checkout' button (shows a toast 'Coming soon!'). "
            "Persist cart to localStorage. Update badge in real-time."
        ),
    },
    "multistep_wizard": {
        "category": "inject",
        "name": "Multi-step Form Wizard",
        "desc": (
            "Create a multi-step wizard overlay with 3-4 steps: "
            "Step 1: Personal Info (name, email fields). "
            "Step 2: Preferences (checkboxes for newsletter, notifications). "
            "Step 3: Review (show all entered data in a summary). "
            "Show a step progress bar at top (Step 1 of 3 — circles connected by lines). "
            "Validate each step before allowing Next. "
            "Previous button preserves entered data. "
            "Final Submit shows a success message."
        ),
    },
    "dashboard_counters": {
        "category": "inject",
        "name": "Real-time Dashboard Counters",
        "desc": (
            "Create a dashboard bar (or floating widget) with 3-4 metric cards: "
            "- 'Visitors' starting at ~1,247 "
            "- 'Page Views' starting at ~3,891 "
            "- 'Avg Time' starting at '2:34' "
            "- 'Bounce Rate' starting at '34.2%'. "
            "Animate numbers counting up from 0 on first view (IntersectionObserver). "
            "Update metrics every 5 seconds with small random deltas. "
            "Add colored mini-sparkline bars (3-5 bars of varying height) below each number."
        ),
    },
    "particle_effects": {
        "category": "inject",
        "name": "Interactive Particle System",
        "desc": (
            "Create a <canvas> element behind the hero section or as a full-page background "
            "(position:fixed, z-index:-1). "
            "Spawn 50-80 particles with random positions, sizes (1-3px), and velocities. "
            "Each particle drifts slowly. Draw connection lines between particles within 120px distance. "
            "On mousemove: particles within 100px of cursor gently push away. "
            "On click: burst 10 new particles from click position. "
            "Use requestAnimationFrame for smooth 60fps animation. "
            "Reduce particle count on mobile (30 particles). "
            "Use subtle colors (rgba with low alpha)."
        ),
    },
}

# Sorted lists for stable random selection
_ENHANCE_KEYS = sorted(k for k, v in JS_FEATURE_CATALOG.items() if v["category"] == "enhance")
_INJECT_KEYS = sorted(k for k, v in JS_FEATURE_CATALOG.items() if v["category"] == "inject")


# ---------------------------------------------------------------------------
# Feature selection
# ---------------------------------------------------------------------------

def select_features(project_name: str, seed: int = 42) -> list[str]:
    """Deterministically select 4-7 features for a project.

    Ensures: at least 1 enhance + at least 2 inject features.
    Uses project_name as part of seed for reproducibility.
    """
    rng = random.Random(f"{seed}:{project_name}")

    n_total = rng.randint(4, 7)
    n_enhance = rng.randint(1, min(3, n_total - 2))
    n_inject = n_total - n_enhance

    selected = rng.sample(_ENHANCE_KEYS, min(n_enhance, len(_ENHANCE_KEYS)))
    selected += rng.sample(_INJECT_KEYS, min(n_inject, len(_INJECT_KEYS)))
    rng.shuffle(selected)
    return selected


def format_feature_instructions(features: list[str]) -> str:
    """Format selected features into numbered instructions for the prompt."""
    lines = []
    for i, key in enumerate(features, 1):
        feat = JS_FEATURE_CATALOG[key]
        category_label = "ENHANCE existing elements" if feat["category"] == "enhance" else "INJECT new component"
        lines.append(
            f"### Feature {i}: {feat['name']}  [{category_label}]\n"
            f"{feat['desc']}\n"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

JS_GENERATION_PROMPT = """\
You are a senior front-end engineer. You will be given the HTML structure (DOM skeleton) of an existing website.

Your task: write a complete `main.js` file that implements ALL of the required features listed below.

## REQUIRED FEATURES — implement ALL of these:

{feature_instructions}

## Implementation rules for each feature type:

### [ENHANCE existing elements]
Analyze the HTML skeleton below. If matching elements exist (nav, form, table, etc.), implement the feature using those elements. If no matching elements exist for a particular enhance feature, implement a simplified version or skip it — add a comment explaining why.

### [INJECT new component]
Create all necessary DOM elements dynamically via JavaScript (createElement, appendChild). These features do NOT require any pre-existing HTML — you build the UI entirely in JS. Position injected elements appropriately (fixed positioning, prepend/append to body, insert into header, etc.).

## Hard constraints

1. **Vanilla JS only** — no jQuery, no React, no frameworks. Use `document.querySelector`, `addEventListener`, etc.
2. **ES6+ syntax** — `const`/`let`, arrow functions, template literals, destructuring.
3. **Self-contained** — each feature must be wrapped in its own function or IIFE with null checks.
4. **Defensive** — always check if elements exist before operating on them: `const el = document.querySelector('.x'); if (el) { ... }`.
5. **No external dependencies** — no CDN imports, no fetch to external APIs, no remote URLs.
6. **DOMContentLoaded** — wrap everything in `document.addEventListener('DOMContentLoaded', () => { ... })`.
7. **Readable** — add a clear comment header for each feature section (e.g., `// === Feature: Dark/Light Theme Toggle ===`).
8. **Inject CSS via JS** — when features need styling, create a <style> element and append it to <head>. Do NOT modify the HTML file.
9. **localStorage** — use it for persistence where specified (theme preference, cart data, etc.).
10. **Size: 150-500 lines** — implement all features substantively. Don't stub them out.

## Output format

Return ONLY the JavaScript code. No markdown fences, no explanations, no HTML modifications.
Start directly with `// main.js` and the code.

## Website HTML skeleton to analyze

{code_context}
"""


# ---------------------------------------------------------------------------
# HTML skeleton extraction (unchanged from previous version)
# ---------------------------------------------------------------------------

_SKELETON_KEEP_ATTRS = {
    "id", "class", "href", "src", "type", "name", "placeholder", "role",
    "for", "action", "method", "alt", "title", "data-target", "data-toggle",
    "aria-label", "aria-expanded", "aria-controls",
}


def _html_to_skeleton(html_code: str) -> str:
    """Extract DOM structure skeleton from HTML, stripping inline CSS."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_code, "html.parser")

    for tag in soup.find_all("style"):
        tag.decompose()
    for tag in soup.find_all("svg"):
        tag.replace_with("[svg]")
    for tag in soup.find_all(True):
        attrs = dict(tag.attrs)
        for attr in attrs:
            if attr not in _SKELETON_KEEP_ATTRS and not attr.startswith(("aria-", "data-")):
                del tag[attr]
    for text_node in soup.find_all(string=True):
        t = text_node.strip()
        if len(t) > 100:
            text_node.replace_with(t[:60] + "...")

    # Deduplicate: same-class sibling elements — keep first 3, collapse rest
    for parent in soup.find_all(True):
        children = [c for c in parent.children if hasattr(c, "name") and c.name]
        seen: dict[tuple, list] = {}
        for child in children:
            key = (child.name, tuple(sorted(child.get("class") or [])))
            seen.setdefault(key, []).append(child)
        for key, group in seen.items():
            if len(group) > 3:
                for extra in group[3:]:
                    extra.decompose()
                group[2].insert_after(f"<!-- ...{len(group) - 3} more {key[0]} items -->")

    result = re.sub(r"\n\s*\n+", "\n", str(soup))
    return re.sub(r"  +", " ", result)


def build_code_context(project_dir: Path, max_chars: int = 20000) -> str:
    """Build a compact code context from project files."""
    code_items = read_code_bundle(project_dir)
    chunks = []
    remaining = max_chars

    priority = {".html": 0, ".htm": 0, ".css": 1, ".js": 2}
    code_items.sort(key=lambda x: (priority.get(Path(x["path"]).suffix.lower(), 9), x["path"]))

    for item in code_items:
        if remaining <= 0:
            break
        suffix = Path(item["path"]).suffix.lower()
        code = item["code"]
        if suffix in (".html", ".htm"):
            code = _html_to_skeleton(code)
        if len(code) > remaining:
            code = code[:remaining] + "\n<!-- ... truncated ... -->"
        chunks.append(f'--- {item["path"]} ---\n{code}')
        remaining -= len(code)

    return "\n\n".join(chunks)


# ---------------------------------------------------------------------------
# JS generation
# ---------------------------------------------------------------------------

_RETRY_DELAYS = [10, 30, 60]  # seconds between retries


def generate_js(
    project_dir: Path,
    model: str,
    client,
    features: list[str],
) -> str | None:
    """Generate main.js content for a project using LLM.

    Retries up to 3 times on rate-limit / timeout / transient errors.
    """
    code_context = build_code_context(project_dir)
    if not code_context.strip():
        return None

    feature_instructions = format_feature_instructions(features)
    prompt = (
        JS_GENERATION_PROMPT
        .replace("{feature_instructions}", feature_instructions)
        .replace("{code_context}", code_context)
    )

    messages = [
        {
            "role": "system",
            "content": (
                "You write clean, functional Vanilla JavaScript for existing websites. "
                "You implement ALL requested features completely — never skip or stub out features."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    last_error = None
    for attempt in range(1 + len(_RETRY_DELAYS)):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=12288,
                temperature=0.7,
            )
            content = response.choices[0].message.content or ""

            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r'^```\w*\n?', '', content)
                content = re.sub(r'\n?```\s*$', '', content)

            result = content.strip()
            if result:
                return result
            # Empty response — treat as transient failure, retry
            last_error = "empty response"

        except Exception as e:
            last_error = str(e)
            err_lower = last_error.lower()
            # Non-retryable errors: invalid API key, model not found, etc.
            if any(kw in err_lower for kw in ["invalid api key", "authentication", "model not found"]):
                print(f"  LLM fatal error: {e}")
                return None

        # Retry with backoff
        if attempt < len(_RETRY_DELAYS):
            delay = _RETRY_DELAYS[attempt]
            print(f"  LLM error (attempt {attempt+1}): {last_error} — retrying in {delay}s")
            time.sleep(delay)

    print(f"  LLM failed after {1 + len(_RETRY_DELAYS)} attempts: {last_error}")
    return None


def process_project(
    project_dir: Path,
    output_dir: Path,
    model: str,
    client,
    seed: int = 42,
) -> dict:
    """Process a single project: copy + select features + generate JS."""
    name = project_dir.name
    out = output_dir / name

    # Skip if output already has a main.js (previous successful run)
    if (out / "main.js").exists():
        return {"project": name, "status": "skipped"}

    # Select features for this project
    features = select_features(name, seed=seed)

    # Copy project (cleans remote URLs via sanitize_project_files)
    if out.exists():
        shutil.rmtree(out)
    copy_project(project_dir, out)

    js_content = generate_js(out, model, client, features)
    if not js_content:
        return {"project": name, "status": "generation_failed", "assigned_features": features}

    (out / "main.js").write_text(js_content, encoding="utf-8")

    # Inject <script src="main.js"> into all HTML files
    for html_file in out.glob("*.html"):
        html = html_file.read_text(encoding="utf-8", errors="replace")
        if '<script src="main.js">' not in html:
            if "</body>" in html:
                html = html.replace("</body>", '  <script src="main.js"></script>\n</body>')
            else:
                html += '\n<script src="main.js"></script>'
            html_file.write_text(html, encoding="utf-8")

    return {
        "project": name,
        "status": "ok",
        "assigned_features": features,
        "js_lines": len(js_content.splitlines()),
        "js_size": len(js_content),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Add Vanilla JS to existing HTML/CSS projects using LLM")
    parser.add_argument("--input-dir", required=True, help="Directory with project subdirs")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--concurrency", type=int, default=3, help="Concurrent LLM calls")
    parser.add_argument("--limit", type=int, default=None, help="Limit projects to process")
    parser.add_argument("--model", default=None, help="Override model (default: from env)")
    parser.add_argument("--seed", type=int, default=42, help="Seed for feature selection")
    args = parser.parse_args()

    maybe_load_env()
    api_key, base_url, env_model = ensure_api_env()
    model = args.model or env_model

    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=180.0)

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    projects = sorted(d for d in input_dir.iterdir() if d.is_dir() and (d / "index.html").exists())
    if args.limit:
        projects = projects[:args.limit]

    print(f"Adding JS to {len(projects)} projects (model={model}, concurrency={args.concurrency})")
    print(f"Feature catalog: {len(_ENHANCE_KEYS)} enhance + {len(_INJECT_KEYS)} inject = {len(JS_FEATURE_CATALOG)} total")

    results = []
    results_path = output_dir / "add_js_results.jsonl"
    results_lock = threading.Lock()

    def _append_result(result):
        """Thread-safe: append result to list and immediately write to JSONL."""
        with results_lock:
            results.append(result)
            with open(results_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(result, ensure_ascii=False) + "\n")

    def _log_result(i, result):
        feats = result.get("assigned_features", [])
        js_lines = result.get("js_lines", 0)
        print(f"[{i}/{len(projects)}] {result['project']}: {result['status']} "
              f"({js_lines} lines, {len(feats)} features, {result['elapsed']:.1f}s)")

    def _process_one(proj):
        t0 = time.time()
        try:
            result = process_project(proj, output_dir, model, client, seed=args.seed)
        except Exception as exc:
            result = {"project": proj.name, "status": "error", "error": str(exc)}
        result["elapsed"] = round(time.time() - t0, 1)
        return result

    # Clear results file (fresh run; skipped projects won't re-appear)
    results_path.write_text("", encoding="utf-8")

    if args.concurrency <= 1:
        for i, proj in enumerate(projects, 1):
            result = _process_one(proj)
            _append_result(result)
            _log_result(i, result)
    else:
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            futures = {executor.submit(_process_one, proj): proj for proj in projects}
            for i, future in enumerate(as_completed(futures), 1):
                try:
                    result = future.result()
                except Exception as exc:
                    proj = futures[future]
                    result = {"project": proj.name, "status": "error", "error": str(exc), "elapsed": 0}
                _append_result(result)
                _log_result(i, result)

    statuses = Counter(r["status"] for r in results)
    print(f"\nDone: {statuses}")

    # Print feature distribution
    all_feats = Counter()
    for r in results:
        for f_name in r.get("assigned_features", []):
            all_feats[f_name] += 1
    if all_feats:
        print("\nFeature distribution:")
        for feat, count in all_feats.most_common():
            print(f"  {feat}: {count}")


if __name__ == "__main__":
    main()
