#!/usr/bin/env python3
"""Reconstruct complete HTML with CSS from WebCode2M text + bbox fields.

The bbox field contains per-element computed styles and precise coordinates.
This script merges them back into the HTML to produce self-contained pages
that render close to the original WebCode2M reference screenshots.
"""
import json
import re
from bs4 import BeautifulSoup, NavigableString
from pathlib import Path


INLINE_TAGS = {"span", "a", "strong", "em", "b", "i", "code", "small", "label",
               "abbr", "cite", "sub", "sup", "mark", "time", "var", "kbd", "s", "u"}

BLOCK_CONTAINER_TAGS = {"div", "section", "article", "main", "aside", "header",
                        "footer", "nav", "form", "fieldset", "ul", "ol", "dl",
                        "table", "thead", "tbody", "tfoot", "tr", "figure"}


def infer_display(bbox_node):
    """Infer CSS display/layout properties from children positions."""
    children = bbox_node.get("children", [])
    if len(children) < 2:
        return ""

    valid = [c for c in children if c.get("bbox") and len(c["bbox"]) == 4]
    if len(valid) < 2:
        return ""

    # Don't add flex to containers of inline elements — they flow naturally
    child_types = [c.get("type", "div") for c in valid]
    if all(t in INLINE_TAGS for t in child_types):
        return ""

    # Don't add flex to table rows — they handle layout themselves
    parent_type = bbox_node.get("type", "")
    if parent_type in ("tr", "thead", "tbody", "tfoot", "table"):
        return ""

    # Check first few children for horizontal arrangement
    check = valid[:min(4, len(valid))]
    ys = [c["bbox"][1] for c in check]
    xs = [c["bbox"][0] for c in check]

    y_range = max(ys) - min(ys)
    x_range = max(xs) - min(xs)

    # Only infer flex if children are clearly block-level and horizontally placed
    if y_range < 15 and x_range > 50:
        # Additional check: children should be substantial (not just tiny inline bits)
        widths = [c["bbox"][2] for c in check]
        if min(widths) > 30:
            return "display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px"

    return ""


def compute_style(bbox_node, parent_bbox=None, is_root=False):
    """Build complete inline style from bbox data."""
    parts = []

    # Original computed style from dataset
    orig = bbox_node.get("style") or ""
    if orig:
        parts.append(orig.rstrip(";"))

    bbox = bbox_node.get("bbox", [])
    if not bbox or len(bbox) != 4:
        return "; ".join(parts) if parts else ""

    x, y, w, h = bbox

    # Width constraints
    if parent_bbox and len(parent_bbox) == 4:
        pw = parent_bbox[2]
        if w > 0 and w < pw * 0.95:
            parts.append(f"width: {w}px")
        if w > 0:
            parts.append(f"max-width: {w}px")
    elif is_root and w > 0:
        parts.append(f"max-width: {w}px")

    # Flex layout inference
    layout = infer_display(bbox_node)
    if layout:
        parts.append(layout)

    return "; ".join(parts)


def walk_and_inject(html_node, bbox_node, parent_bbox=None, is_root=False):
    """Recursively walk HTML tree and bbox tree in parallel, injecting styles."""
    if not html_node or not bbox_node:
        return

    # Compute and set style
    style = compute_style(bbox_node, parent_bbox, is_root)
    if style and hasattr(html_node, "attrs"):
        html_node["style"] = style

    # Match HTML children to bbox children
    html_children = [
        c for c in html_node.children
        if hasattr(c, "name") and c.name is not None
    ]
    bbox_children = bbox_node.get("children", [])

    current_bbox = bbox_node.get("bbox")

    for hc, bc in zip(html_children, bbox_children):
        walk_and_inject(hc, bc, parent_bbox=current_bbox)


def reconstruct_html(text: str, bbox_json: str | dict) -> str:
    """Main entry: merge text HTML with bbox styles to produce complete page.

    Args:
        text: The 'text' field from WebCode2M (HTML string)
        bbox_json: The 'bbox' field (JSON string or dict)

    Returns:
        Complete self-contained HTML string with all styles inlined.
    """
    if isinstance(bbox_json, str):
        bbox_data = json.loads(bbox_json)
    else:
        bbox_data = bbox_json

    soup = BeautifulSoup(text, "html.parser")

    # Find the body or root element
    body = soup.body or soup

    # Inject styles from bbox tree
    walk_and_inject(body, bbox_data, is_root=True)

    # Add base reset stylesheet
    style_tag = soup.new_tag("style")
    style_tag.string = """
* { box-sizing: border-box; }
body { margin: 8px; }
img { max-width: 100%; height: auto; }
table { border-collapse: collapse; }
td, th { vertical-align: top; padding: 2px 4px; }
a { color: #0366d6; text-decoration: none; }
a:hover { text-decoration: underline; }
"""
    # Insert at beginning
    if soup.head:
        soup.head.append(style_tag)
    else:
        head = soup.new_tag("head")
        head.append(style_tag)
        if soup.html:
            soup.html.insert(0, head)
        else:
            soup.insert(0, style_tag)

    return str(soup)


if __name__ == "__main__":
    import sys
    import requests
    from playwright.sync_api import sync_playwright

    proxy = "socks5h://127.0.0.1:13659"
    offset = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    print(f"Fetching row at offset={offset}...")
    url = f"https://datasets-server.huggingface.co/rows?dataset=xcodemind/webcode2m&config=default&split=train&offset={offset}&length=1"
    resp = requests.get(url, timeout=15, proxies={"http": proxy, "https": proxy})
    row = resp.json()["rows"][0]["row"]

    text = row["text"]
    bbox = row["bbox"]
    scale = row["scale"]  # [width, height]

    print(f"  HTML: {len(text)} chars, viewport: {scale}")

    # Reconstruct
    result = reconstruct_html(text, bbox)

    out_dir = Path("local_trials/merge_test")
    out_dir.mkdir(exist_ok=True)

    out_html = out_dir / f"perfect_{offset}.html"
    out_html.write_text(result, encoding="utf-8")
    print(f"  Output: {out_html} ({len(result)} chars)")

    # Render
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": scale[0], "height": 800})
        page.goto(f"file://{out_html.resolve()}", wait_until="domcontentloaded")
        page.wait_for_timeout(500)
        page.screenshot(path=str(out_html.with_suffix(".png")), full_page=True)
        browser.close()

    print(f"  Screenshot: {out_html.with_suffix('.png')}")

    # Also download reference for comparison
    img_url = row["image"]["src"]
    resp2 = requests.get(img_url, timeout=30, proxies={"http": proxy, "https": proxy})
    ref_path = out_dir / f"perfect_{offset}_ref.png"
    ref_path.write_bytes(resp2.content)
    print(f"  Reference: {ref_path}")
