#!/usr/bin/env python3
"""统一资源清洗模块。

将项目中的所有远程/缺失资源替换为本地占位或删除，使项目完全离线可渲染。

处理规则：
1. 远程图片、本地缺失图片 → picsum.photos 占位图（4 层尺寸解析）
2. 远程 CSS → 下载到 resources/（有 session 时），否则删除
3. 远程 JS → 下载到 resources/（有 session 时），否则删除
4. 远程字体 link、@import、@font-face → 删除
5. iframe → 占位 div
6. 追踪/分析脚本 → 删除
7. 外部链接 → 中性化

用法 (CLI):
    python3 preprocess/clean_resources.py --input-dir /path/to/sp --dry-run
    python3 preprocess/clean_resources.py --input-dir /path/to/sp

用法 (import):
    from preprocess.clean_resources import clean_project_resources
    result = clean_project_resources(project_dir, session=None)
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Picsum constants (same pool as playwright_crawl._picsum_url)
# ---------------------------------------------------------------------------
_PICSUM_UNAVAILABLE = {
    86, 97, 105, 138, 148, 150, 188, 200, 205, 207, 210, 224, 226, 245, 246,
    262, 285, 286, 298, 303, 332, 333, 346, 359, 394, 414, 422, 438, 449,
    462, 463, 470, 489, 540, 561, 578, 587, 589, 592, 595, 597, 601, 624,
    632, 636, 644, 647, 673, 697, 706, 707, 708, 709, 710, 711, 712, 713,
    714, 720, 725, 734, 745, 746, 747, 748, 749, 750, 751, 752, 753, 754,
    759, 761, 762, 763, 771, 792, 801, 812, 843, 850, 854, 895, 897, 899,
    917, 920, 934, 947, 956, 963, 968, 1007, 1017, 1030, 1034, 1046,
}
_PICSUM_IDS = [i for i in range(0, 1085) if i not in _PICSUM_UNAVAILABLE]
_PICSUM_SIZES = [
    (300, 200), (400, 300), (350, 250), (250, 250),
    (200, 150), (150, 150), (320, 240), (280, 180),
    (360, 240), (200, 200), (240, 160), (180, 180),
    (300, 300), (400, 250), (350, 200), (260, 200),
]

# 不清理的域名
SAFE_DOMAINS_RE = re.compile(
    r'(picsum\.photos|w3\.org|ogp\.me|schema\.org|gmpg\.org|xmlns)',
    re.IGNORECASE,
)

# 追踪/分析脚本关键词
TRACKING_KEYWORDS = [
    "google-analytics", "googletagmanager", "gtag(", "ga(",
    "fbq(", "facebook.net", "doubleclick", "googlesyndication",
    "hotjar", "clarity.ms", "segment.com", "mixpanel",
    "amplitude", "intercom", "drift", "hubspot", "pardot",
    "optimizely", "crazyegg", "mouseflow", "lucky_orange",
    "cookie", "consent", "gdpr",
]

TRACKING_DOMAINS = [
    "google-analytics.com", "googletagmanager.com", "googlesyndication.com",
    "doubleclick.net", "facebook.net", "connect.facebook.net",
    "hotjar.com", "clarity.ms", "segment.com", "cdn.segment.com",
    "mixpanel.com", "amplitude.com", "intercom.io",
    "js.hs-scripts.com", "js.hs-analytics.net",
]

# 字体相关域名
FONT_DOMAINS = [
    "fonts.googleapis.com", "fonts.gstatic.com", "fonts.bunny.net",
    "use.typekit.net", "use.fontawesome.com",
]

_FONT_FILE_EXTS = {".woff", ".woff2", ".ttf", ".otf", ".eot"}
_IMG_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".ico", ".svg"}
_KEEP_RESOURCE_EXTS = {".css", ".js", ".jsx", ".ts", ".tsx"}


# ---------------------------------------------------------------------------
# Picsum URL generation with 10-layer dimension parsing
# ---------------------------------------------------------------------------

def _picsum_url(idx: int, w: int = 0, h: int = 0) -> str:
    """Generate a deterministic picsum.photos URL."""
    photo_id = _PICSUM_IDS[idx % len(_PICSUM_IDS)]
    if w > 0 and h > 0:
        w = max(50, min(w, 2000))
        h = max(50, min(h, 2000))
    else:
        w, h = _PICSUM_SIZES[idx % len(_PICSUM_SIZES)]
    return f"https://picsum.photos/id/{photo_id}/{w}/{h}"


def _parse_srcset_max_width(srcset: str) -> int:
    """从 srcset 属性中提取最大的宽度描述符（如 '320w'）。"""
    max_w = 0
    for part in srcset.split(","):
        part = part.strip()
        m = re.search(r'(\d+)w\s*$', part)
        if m:
            max_w = max(max_w, int(m.group(1)))
    return max_w


def _read_image_dimensions_from_header(session, url: str) -> tuple[int, int]:
    """HTTP GET 前 32KB，从 JPEG/PNG/GIF/WebP 文件头读取像素尺寸。"""
    import struct
    try:
        resp = session.get(url, timeout=(3, 5), stream=True,
                           headers={"Range": "bytes=0-32767"})
        data = resp.content[:32768]
        if len(data) < 8:
            return 0, 0
    except Exception:
        return 0, 0

    # PNG: 固定位置 (width @ 16, height @ 20)
    if data[:8] == b'\x89PNG\r\n\x1a\n' and len(data) >= 24:
        w = struct.unpack('>I', data[16:20])[0]
        h = struct.unpack('>I', data[20:24])[0]
        return w, h

    # GIF: 固定位置 (width @ 6, height @ 8)
    if data[:4] in (b'GIF8',) and len(data) >= 10:
        w = struct.unpack('<H', data[6:8])[0]
        h = struct.unpack('<H', data[8:10])[0]
        return w, h

    # JPEG: 扫描 SOF markers
    if data[:2] == b'\xff\xd8':
        i = 2
        while i < len(data) - 9:
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            # SOF0-SOF3, SOF5-SOF7, SOF9-SOF11, SOF13-SOF15
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                          0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h = struct.unpack('>H', data[i+5:i+7])[0]
                w = struct.unpack('>H', data[i+7:i+9])[0]
                return w, h
            if marker == 0xD9:  # EOI
                break
            if marker in (0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0x01):
                i += 2
                continue
            if i + 3 < len(data):
                seg_len = struct.unpack('>H', data[i+2:i+4])[0]
                i += 2 + seg_len
            else:
                break

    # WebP: RIFF header
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP' and len(data) >= 30:
        # VP8 (lossy)
        if data[12:16] == b'VP8 ' and len(data) >= 30:
            w = struct.unpack('<H', data[26:28])[0] & 0x3FFF
            h = struct.unpack('<H', data[28:30])[0] & 0x3FFF
            return w, h
        # VP8L (lossless)
        if data[12:16] == b'VP8L' and len(data) >= 25:
            bits = struct.unpack('<I', data[21:25])[0]
            w = (bits & 0x3FFF) + 1
            h = ((bits >> 14) & 0x3FFF) + 1
            return w, h

    return 0, 0


# CSS 选择器尺寸缓存：{html_file_path: {selector: (w, h)}}
_css_dim_cache: dict[str, dict[str, tuple[int, int]]] = {}


def _build_css_dim_map(soup) -> dict[str, tuple[int, int]]:
    """从 <style> 块中提取所有带 width/height 的选择器 → 尺寸映射。

    返回 {".hero-img": (800, 400), "#logo": (120, 60), ...}
    """
    dim_map: dict[str, tuple[int, int]] = {}
    for style_tag in soup.find_all("style"):
        css_text = style_tag.string or ""
        if not css_text:
            continue
        # 简单正则：匹配 selector { ... width: Npx ... height: Npx ... }
        for m in re.finditer(
            r'([.#][\w-]+)\s*\{([^}]*)\}', css_text
        ):
            selector = m.group(1)
            block = m.group(2)
            wm = re.search(r'(?:^|;\s*)width:\s*(\d+)px', block)
            hm = re.search(r'(?:^|;\s*)height:\s*(\d+)px', block)
            if wm or hm:
                w = int(wm.group(1)) if wm else 0
                h = int(hm.group(1)) if hm else 0
                dim_map[selector] = (w, h)
    return dim_map


def parse_img_dimensions(tag, soup=None, session=None) -> tuple[int, int]:
    """10 层尺寸解析，逐层 fallback 直到获取 w 和 h。

    Layer 1: HTML width/height 属性
    Layer 2: inline style width/height
    Layer 3: CSS class 中的尺寸 hint（如 wp-image-655x533）
    Layer 4: URL 参数/文件名中的尺寸
    Layer 5: srcset 宽度描述符（取最大 w，按 3:2 推算 h）
    Layer 6: data-* 维度属性（data-width, data-orig-size 等）
    Layer 7: <style> 块中的 CSS 选择器匹配
    Layer 8: 父容器 inline style 尺寸
    Layer 9: HTTP HEAD 读图片文件头（需要 session，最后手段）
    Layer 10: aspect-ratio + 单边尺寸推算
    """
    w, h = 0, 0

    # Layer 1: HTML width/height attributes
    try:
        w_raw = tag.get("width", "")
        h_raw = tag.get("height", "")
        if str(w_raw).isdigit():
            w = int(w_raw)
        if str(h_raw).isdigit():
            h = int(h_raw)
    except (ValueError, TypeError):
        pass

    # Layer 2: inline style
    if (w == 0 or h == 0) and tag.get("style"):
        style = tag["style"]
        wm = re.search(r'width:\s*(\d+)px', style)
        hm = re.search(r'height:\s*(\d+)px', style)
        if wm:
            w = int(wm.group(1))
        if hm:
            h = int(hm.group(1))

    # Layer 3: CSS class hints (e.g. wp-image-655x533)
    if w == 0 or h == 0:
        cls = " ".join(tag.get("class") or [])
        dim_m = re.search(r'(\d{2,4})x(\d{2,4})', cls)
        if dim_m:
            w, h = int(dim_m.group(1)), int(dim_m.group(2))

    # Layer 4: URL-embedded dimensions
    if w == 0 or h == 0:
        first_url = tag.get("src") or tag.get("data-src") or ""
        if first_url:
            wm = re.search(r'[?&](?:width|w)=(\d+)', first_url)
            hm = re.search(r'[?&](?:height|h)=(\d+)', first_url)
            if wm:
                w = int(wm.group(1))
            if hm:
                h = int(hm.group(1))
        if w == 0 or h == 0:
            dim_m = re.search(r'(\d{2,4})x(\d{2,4})\.\w+$', first_url)
            if dim_m:
                w, h = int(dim_m.group(1)), int(dim_m.group(2))

    # Layer 5: srcset 宽度描述符
    if w == 0 or h == 0:
        srcset = tag.get("srcset", "")
        if srcset:
            max_w = _parse_srcset_max_width(srcset)
            if max_w > 0 and w == 0:
                w = max_w
            # sizes 属性可能有默认显示宽度，优先用它
            sizes = tag.get("sizes", "")
            if sizes and w == 0:
                # 取 sizes 的最后一个值（默认值），如 "(max-width:600px) 480px, 800px" → 800
                sm = re.search(r'(\d+)px\s*$', sizes)
                if sm:
                    w = int(sm.group(1))

    # Layer 6: data-* 维度属性
    if w == 0 or h == 0:
        # data-width / data-height
        for dw_attr in ("data-width", "data-full-width", "data-orig-width",
                         "data-original-width", "data-default-width"):
            dw = tag.get(dw_attr, "")
            if str(dw).isdigit() and int(dw) > 0 and w == 0:
                w = int(dw)
                break
        for dh_attr in ("data-height", "data-full-height", "data-orig-height",
                         "data-original-height", "data-default-height"):
            dh = tag.get(dh_attr, "")
            if str(dh).isdigit() and int(dh) > 0 and h == 0:
                h = int(dh)
                break
        # data-orig-size="1024,768" (WordPress/Jetpack)
        if w == 0 or h == 0:
            orig_size = tag.get("data-orig-size", "")
            if orig_size:
                parts = re.match(r'(\d+)\s*[,x]\s*(\d+)', orig_size)
                if parts:
                    if w == 0:
                        w = int(parts.group(1))
                    if h == 0:
                        h = int(parts.group(2))
        # data-large-file / data-medium-file URL 中的尺寸参数
        if w == 0 or h == 0:
            for df_attr in ("data-large-file", "data-medium-file"):
                df_url = tag.get(df_attr, "")
                if df_url:
                    wm = re.search(r'[?&]w=(\d+)', df_url)
                    hm = re.search(r'[?&]h=(\d+)', df_url)
                    if wm and w == 0:
                        w = int(wm.group(1))
                    if hm and h == 0:
                        h = int(hm.group(1))
                    if w > 0 or h > 0:
                        break

    # Layer 7: <style> 块中的 CSS 选择器匹配
    if (w == 0 or h == 0) and soup is not None:
        # 用 id(soup) 缓存，避免每个 img 都重新解析
        soup_key = id(soup)
        if soup_key not in _css_dim_cache:
            _css_dim_cache[soup_key] = _build_css_dim_map(soup)
        dim_map = _css_dim_cache[soup_key]
        if dim_map:
            # 检查 tag 的 class 和 id 是否匹配
            tag_id = tag.get("id", "")
            tag_classes = tag.get("class") or []
            for cls_name in tag_classes:
                key = f".{cls_name}"
                if key in dim_map:
                    cw, ch = dim_map[key]
                    if cw > 0 and w == 0:
                        w = cw
                    if ch > 0 and h == 0:
                        h = ch
                    break
            if (w == 0 or h == 0) and tag_id:
                key = f"#{tag_id}"
                if key in dim_map:
                    cw, ch = dim_map[key]
                    if cw > 0 and w == 0:
                        w = cw
                    if ch > 0 and h == 0:
                        h = ch

    # Layer 8: 父容器 inline style 尺寸
    if w == 0 or h == 0:
        parent = tag.parent
        if parent and parent.get("style"):
            pstyle = parent["style"]
            if w == 0:
                pwm = re.search(r'width:\s*(\d+)px', pstyle)
                if pwm:
                    w = int(pwm.group(1))
            if h == 0:
                phm = re.search(r'height:\s*(\d+)px', pstyle)
                if phm:
                    h = int(phm.group(1))

    # Layer 9: HTTP HEAD 读图片文件头（最后手段，需要 session）
    if (w == 0 or h == 0) and session is not None:
        img_url = tag.get("src") or tag.get("data-src") or ""
        if img_url and (img_url.startswith("http://") or img_url.startswith("https://")):
            hw, hh = _read_image_dimensions_from_header(session, img_url)
            if hw > 0 and w == 0:
                w = hw
            if hh > 0 and h == 0:
                h = hh

    # Layer 10: aspect-ratio + 单边尺寸推算
    if (w == 0 or h == 0) and (w > 0 or h > 0):
        ratio = None
        # 从 inline style 提取 aspect-ratio
        style = tag.get("style", "")
        ar_m = re.search(r'aspect-ratio:\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)', style)
        if ar_m:
            ratio = float(ar_m.group(1)) / float(ar_m.group(2))
        # 从 <style> 块匹配的选择器中提取
        if ratio is None and soup is not None:
            for style_tag in soup.find_all("style"):
                css_text = style_tag.string or ""
                tag_classes = tag.get("class") or []
                tag_id = tag.get("id", "")
                selectors = [f".{c}" for c in tag_classes]
                if tag_id:
                    selectors.append(f"#{tag_id}")
                for sel in selectors:
                    sel_escaped = re.escape(sel)
                    m = re.search(
                        sel_escaped + r'\s*\{([^}]*)\}', css_text
                    )
                    if m:
                        ar_m2 = re.search(
                            r'aspect-ratio:\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)',
                            m.group(1),
                        )
                        if ar_m2:
                            ratio = float(ar_m2.group(1)) / float(ar_m2.group(2))
                            break
                if ratio is not None:
                    break
        if ratio is not None and ratio > 0:
            if w > 0 and h == 0:
                h = int(w / ratio)
            elif h > 0 and w == 0:
                w = int(h * ratio)
        else:
            # 没有 aspect-ratio，用 3:2 默认比例推算缺失的一边
            if w > 0 and h == 0:
                h = int(w * 2 / 3)
            elif h > 0 and w == 0:
                w = int(h * 3 / 2)

    return w, h


def _is_remote(url: str) -> bool:
    return url.startswith("http") or url.startswith("//")


def _is_safe_domain(url: str) -> bool:
    return bool(SAFE_DOMAINS_RE.search(url))


def _is_font_domain(url: str) -> bool:
    return any(d in url for d in FONT_DOMAINS)


def _is_tracking_script(tag) -> bool:
    """Check if a <script> tag is tracking/analytics."""
    src = (tag.get("src") or "").lower()
    text = (tag.string or "").lower()
    for domain in TRACKING_DOMAINS:
        if domain in src:
            return True
    for kw in TRACKING_KEYWORDS:
        if kw in src or kw in text:
            return True
    return False


# ---------------------------------------------------------------------------
# CSS file cleaning
# ---------------------------------------------------------------------------

def _extract_dims_for_css_url(
    url: str,
    css_context: str = "",
    session=None,
    is_background: bool = False,
) -> tuple[int, int]:
    """从 CSS url() 引用推断图片尺寸（对齐 parse_img_dimensions 的 10 层策略）。

    Layer A: URL query 参数 — ?width=300&height=200, ?w=300&h=200
    Layer B: URL/文件名嵌入 — banner-800x600.jpg, image_320x240.png
    Layer C: CSS 规则块上下文 — background-size, width/height 属性
    Layer D: background-size: cover → viewport 尺寸（1280x720）
    Layer E: HTTP HEAD 读图片文件头（需要 session）
    Layer F: HTML 元素匹配 — 用 CSS 选择器在 HTML 中找对应元素的实际渲染尺寸
    Layer G: 单边 + 3:2 默认比例推算
    Layer H: 对于 background-image，默认使用全宽尺寸（1920x1080）而非小图

    Args:
        url: url() 中的路径/URL
        css_context: url() 所在的 CSS 规则块文本（{} 之间的内容）
        session: requests.Session，用于 HTTP HEAD 读图片文件头
        is_background: 是否是 background-image（区别于其他 CSS 图片引用）
    """
    w, h = 0, 0

    # Layer A: URL query 参数
    wm = re.search(r'[?&](?:width|w)=(\d+)', url)
    hm = re.search(r'[?&](?:height|h)=(\d+)', url)
    if wm:
        w = int(wm.group(1))
    if hm:
        h = int(hm.group(1))

    # Layer B: 文件名中的 NxN 模式
    if w == 0 or h == 0:
        dim_m = re.search(r'(\d{2,4})x(\d{2,4})\.\w+', url)
        if dim_m:
            w, h = int(dim_m.group(1)), int(dim_m.group(2))

    # Layer C: CSS 规则上下文中的尺寸属性
    if (w == 0 or h == 0) and css_context:
        # background-size: 300px 200px 或 background-size: 300px（单值）
        bs = re.search(
            r'background-size\s*:\s*(\d{2,4})px(?:\s+(\d{2,4})px)?',
            css_context, re.IGNORECASE,
        )
        if bs:
            if w == 0:
                w = int(bs.group(1))
            if h == 0 and bs.group(2):
                h = int(bs.group(2))

        # width / height 属性（跳过 min-/max- 前缀）
        if w == 0:
            wm2 = re.search(r'(?<![a-z-])width\s*:\s*(\d{2,4})px', css_context, re.IGNORECASE)
            if wm2:
                w = int(wm2.group(1))
        if h == 0:
            hm2 = re.search(r'(?<![a-z-])height\s*:\s*(\d{2,4})px', css_context, re.IGNORECASE)
            if hm2:
                h = int(hm2.group(1))

    # Layer D: background-size: cover / contain → 推断为视口尺寸
    if (w == 0 or h == 0) and css_context:
        if re.search(r'background-size\s*:\s*cover', css_context, re.IGNORECASE):
            if w == 0:
                w = 1280
            if h == 0:
                h = 720
        elif re.search(r'background-size\s*:\s*contain', css_context, re.IGNORECASE):
            if w == 0:
                w = 1280
            if h == 0:
                h = 720

    # Layer E: HTTP HEAD 读图片文件头（需要 session）
    if (w == 0 or h == 0) and session is not None:
        if url.startswith("http://") or url.startswith("https://"):
            hw, hh = _read_image_dimensions_from_header(session, url)
            if hw > 0 and w == 0:
                w = hw
            if hh > 0 and h == 0:
                h = hh

    # Layer F: 只有一边时按 3:2 补另一边
    if w > 0 and h == 0:
        h = max(50, w * 2 // 3)
    elif h > 0 and w == 0:
        w = max(50, h * 3 // 2)

    # Layer G: 对于 background-image 无任何尺寸信息，使用全宽默认值
    if w == 0 and h == 0 and is_background:
        w, h = 1920, 1080

    return w, h


def _clean_css_text(css_text: str, img_idx: int, session=None) -> tuple[str, int]:
    """Clean remote references inside a CSS string. Returns (cleaned_css, new_img_idx)."""
    # Remove @import url("https://...")
    css_text = re.sub(
        r'@import\s+url\s*\(\s*["\']?https?://(?!picsum\.photos)[^"\')\s]+["\']?\s*\)\s*;?',
        '', css_text, flags=re.IGNORECASE,
    )
    # Remove @font-face with remote src
    css_text = re.sub(
        r'@font-face\s*\{[^}]*?src\s*:[^}]*?https?://[^}]+?\}',
        '', css_text, flags=re.IGNORECASE | re.DOTALL,
    )
    # Replace remote url() — images → picsum, fonts → drop
    _box = [img_idx]

    def _get_rule_context(text: str, pos: int) -> str:
        brace_start = text.rfind("{", 0, pos)
        if brace_start == -1:
            return ""
        brace_end = text.find("}", pos)
        if brace_end == -1:
            return ""
        return text[brace_start:brace_end + 1]

    def _replace_url(m):
        inner = m.group(1).strip("'\"")
        if not _is_remote(inner):
            return m.group(0)
        if _is_safe_domain(inner):
            return m.group(0)
        if any(inner.lower().endswith(ext) for ext in _FONT_FILE_EXTS):
            return "url()"  # drop remote font — browser falls back
        css_context = _get_rule_context(css_text, m.start())
        is_bg = bool(re.search(r'background(-image)?\s*:', css_context, re.IGNORECASE))
        w, h = _extract_dims_for_css_url(inner, css_context, session=session, is_background=is_bg)
        placeholder = _picsum_url(_box[0], w, h)
        _box[0] += 1
        return f"url({placeholder})"

    css_text = re.sub(r'url\(["\']?([^)]+?)["\']?\)', _replace_url, css_text)
    return css_text, _box[0]


def _clean_css_relative_urls(
    css_text: str,
    css_file: Path,
    project_dir: Path,
    img_idx: int,
    stats: dict[str, int],
    session=None,
) -> tuple[str, int]:
    """修复 CSS 文件中断裂的相对 url() 引用。

    在 _clean_css_text 处理完远程 URL 之后调用。检查剩余的相对路径
    （如 ../images/banner.gif）是否指向存在的本地文件，不存在则：
    - 图片类 → picsum 占位
    - 字体类 → url()（空，浏览器 fallback）
    """
    _box = [img_idx]
    css_dir = css_file.parent

    def _get_rule_context(text: str, pos: int) -> str:
        """找到 pos 所在 { ... } 规则块的内容，用于尺寸推断。"""
        # 向前找最近的 '{'
        brace_start = text.rfind("{", 0, pos)
        if brace_start == -1:
            return ""
        # 向后找对应的 '}'
        brace_end = text.find("}", pos)
        if brace_end == -1:
            return ""
        return text[brace_start:brace_end + 1]

    def _replace_relative(m: re.Match) -> str:
        inner = m.group(1).strip("'\"")
        # 跳过已处理的类型
        if not inner or not inner.strip():
            return m.group(0)
        if _is_remote(inner):
            return m.group(0)
        if inner.startswith("data:"):
            return m.group(0)
        if "picsum.photos" in inner:
            return m.group(0)

        # 去掉 query/fragment 再解析路径
        clean_path = inner.split("?")[0].split("#")[0]
        resolved = (css_dir / clean_path).resolve()
        if resolved.exists():
            return m.group(0)

        # 断裂引用 — 按后缀分类替换
        ext = Path(clean_path).suffix.lower()
        # .svg#fontawesome 这类是字体引用，不是图片
        if ext == ".svg" and "#" in inner:
            stats["css_broken_fonts_fixed"] = stats.get("css_broken_fonts_fixed", 0) + 1
            return "url()"
        if ext in _IMG_EXTS:
            css_context = _get_rule_context(css_text, m.start())
            is_bg = bool(re.search(r'background(-image)?\s*:', css_context, re.IGNORECASE))
            w, h = _extract_dims_for_css_url(inner, css_context, session=session, is_background=is_bg)
            placeholder = _picsum_url(_box[0], w, h)
            _box[0] += 1
            stats["css_broken_images_fixed"] = stats.get("css_broken_images_fixed", 0) + 1
            return f"url({placeholder})"
        if ext in _FONT_FILE_EXTS:
            stats["css_broken_fonts_fixed"] = stats.get("css_broken_fonts_fixed", 0) + 1
            return "url()"
        # 未知类型 — 保留原样
        return m.group(0)

    css_text = re.sub(r'url\(["\']?([^)]+?)["\']?\)', _replace_relative, css_text)

    # 清理所有 src 都无效的 @font-face 块（url() 为空说明字体源全断裂了）
    # 删掉整个块，让页面 fallback 到 font-family 的后备字体（通常 sans-serif）
    def _remove_dead_fontface(m: re.Match) -> str:
        block = m.group(0)
        # 如果块内还有非空的 url()，说明有可用字体源，保留
        if re.search(r'url\(\s*["\']?\S+["\']?\s*\)', block):
            return block
        # 所有 url() 都是空的 — 删掉整个 @font-face
        stats["css_dead_fontface_removed"] = stats.get("css_dead_fontface_removed", 0) + 1
        return ""

    css_text = re.sub(
        r'@font-face\s*\{[^}]*\}', _remove_dead_fontface,
        css_text, flags=re.IGNORECASE | re.DOTALL,
    )

    return css_text, _box[0]


# ---------------------------------------------------------------------------
# Download helpers (optional, only if session is provided)
# ---------------------------------------------------------------------------

def _try_download_css(session, url: str, resources_dir: Path, img_idx: int) -> tuple[str | None, int]:
    """Try to download CSS file. Returns (local_path_or_None, updated_img_idx)."""
    try:
        resp = session.get(url, timeout=(5, 10), allow_redirects=True)
        if resp.status_code == 200 and len(resp.content) >= 10:
            h = hashlib.md5(url.encode()).hexdigest()[:8]
            name = Path(urlparse(url).path).name or "style.css"
            name = f"{h}_{name}"
            name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80]
            if not name.endswith(".css"):
                name += ".css"
            css_text = resp.content.decode("utf-8", errors="replace")
            css_text, img_idx = _clean_css_text(css_text, img_idx, session)
            target = resources_dir / name
            target.write_text(css_text, encoding="utf-8")
            return f"./resources/{name}", img_idx
    except Exception:
        pass
    return None, img_idx


def _try_download_js(session, url: str, resources_dir: Path) -> str | None:
    """Try to download JS file. Returns local path or None."""
    try:
        resp = session.get(url, timeout=(5, 10), allow_redirects=True)
        if resp.status_code == 200 and len(resp.content) >= 10:
            h = hashlib.md5(url.encode()).hexdigest()[:8]
            name = Path(urlparse(url).path).name or "script.js"
            name = f"{h}_{name}"
            name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:80]
            if not name.endswith(".js"):
                name += ".js"
            target = resources_dir / name
            target.write_bytes(resp.content)
            return f"./resources/{name}"
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Main: clean one HTML file
# ---------------------------------------------------------------------------

def _clean_html_file(
    html_file: Path,
    resources_dir: Path,
    session,
    img_idx: int,
    stats: dict[str, int],
    dry_run: bool = False,
) -> int:
    """Clean one HTML file. Returns updated img_idx."""
    html = html_file.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")
    modified = False

    # --- Remove IE conditional comments (can't be parsed by BS4) ---
    raw = str(soup)
    cleaned_raw = re.sub(r'<!--\[if[^\]]*\]>.*?<!\[endif\]-->', '', raw, flags=re.DOTALL)
    if cleaned_raw != raw:
        soup = BeautifulSoup(cleaned_raw, "html.parser")
        modified = True

    # --- Remove tracking/analytics scripts ---
    for script in list(soup.find_all("script")):
        if _is_tracking_script(script):
            script.decompose()
            stats["tracking_removed"] += 1
            modified = True

    # --- Remove backend config scripts (useless for static rendering) ---
    _BACKEND_KEYWORDS = (
        "wp-admin", "admin-ajax", "wc_ajax", "wc_add_to_cart",
        "wc_order_attribution", "wp_ajax", "ajaxurl",
        "et_pb_custom", "et_frontend_nonce", "et_ab_log_nonce",
        "woocommerce_params", "wc_cart_fragments_params",
        "mejsL10n", "wp-embed", "wp-emoji",
        "rocket-browser-checker", "rocket-no-cookie",
        "app_id", "api_key", "client_id",
    )
    for script in list(soup.find_all("script")):
        if script.get("src"):
            continue  # only target inline scripts
        text = (script.string or "").lower()
        if not text or len(text) < 20:
            continue
        if any(kw.lower() in text for kw in _BACKEND_KEYWORDS):
            script.decompose()
            stats["backend_config_removed"] = stats.get("backend_config_removed", 0) + 1
            modified = True

    # --- Remote <link> tags ---
    for link in list(soup.find_all("link")):
        href = link.get("href", "")
        if not _is_remote(href):
            continue
        if _is_safe_domain(href):
            continue
        rel = " ".join(link.get("rel") or []).lower()

        # Font links → remove
        if _is_font_domain(href) or "font" in href.lower():
            link.decompose()
            stats["font_links_removed"] += 1
            modified = True
            continue

        # Stylesheet links → try download, else remove
        if "stylesheet" in rel or href.lower().endswith(".css"):
            if session:
                local_path, img_idx = _try_download_css(session, href, resources_dir, img_idx)
                if local_path:
                    link["href"] = local_path
                    stats["css_downloaded"] += 1
                else:
                    link.decompose()
                    stats["css_removed"] += 1
            else:
                link.decompose()
                stats["css_removed"] += 1
            modified = True
            continue

        # Other remote links (favicon, preconnect, etc.) → remove
        link.decompose()
        stats["other_links_removed"] += 1
        modified = True

    # --- Remote <script src="..."> → try download or remove ---
    for script in list(soup.find_all("script", src=True)):
        src = script.get("src", "")
        if not _is_remote(src):
            continue
        if _is_safe_domain(src):
            continue
        if session:
            local_path = _try_download_js(session, src, resources_dir)
            if local_path:
                script["src"] = local_path
                stats["js_downloaded"] += 1
            else:
                script.decompose()
                stats["js_removed"] += 1
        else:
            script.decompose()
            stats["js_removed"] += 1
        modified = True

    # --- Replace images: remote + local missing → picsum ---
    for tag in soup.find_all(["img", "source", "input"]):
        if tag.name == "input" and (tag.get("type") or "").lower() != "image":
            continue
        w, h = parse_img_dimensions(tag, soup=soup, session=session)

        for attr in ("src", "data-src", "data-lazy-src", "data-cke-saved-src",
                      "nitro-lazy-src", "data-original", "data-lazy"):
            val = tag.get(attr)
            if not val or val.startswith("data:"):
                continue
            if "picsum.photos" in val:
                continue

            needs_replace = False
            if _is_remote(val):
                needs_replace = True
            elif val.startswith("./resources/") or val.startswith("resources/"):
                # Check if local file actually exists
                local_path = resources_dir / val.replace("./resources/", "").replace("resources/", "")
                if not local_path.exists():
                    needs_replace = True

            if needs_replace:
                tag[attr] = _picsum_url(img_idx, w, h)
                img_idx += 1
                stats["images_replaced"] += 1
                modified = True

        # Clean srcset
        srcset = tag.get("srcset", "")
        if srcset and ("http" in srcset or "//" in srcset):
            tag["srcset"] = _picsum_url(img_idx, w, h)
            img_idx += 1
            stats["images_replaced"] += 1
            modified = True

    # --- Replace <video>/<audio> remote src ---
    for tag in soup.find_all(["video", "audio"]):
        for attr in ("src", "poster"):
            val = tag.get(attr, "")
            if val and _is_remote(val) and "picsum.photos" not in val:
                tag[attr] = _picsum_url(img_idx)
                img_idx += 1
                stats["media_replaced"] += 1
                modified = True

    # --- iframe → placeholder div ---
    for iframe in list(soup.find_all("iframe")):
        src = iframe.get("src", "")
        if src and _is_remote(src):
            placeholder = soup.new_tag("div")
            placeholder["style"] = (
                "background:#eee;display:flex;align-items:center;justify-content:center;"
                "min-height:200px;border:1px solid #ccc;"
            )
            span = soup.new_tag("span")
            span["style"] = "color:#999;"
            span.string = "Embedded content"
            placeholder.append(span)
            iframe.replace_with(placeholder)
            stats["iframes_replaced"] += 1
            modified = True

    # --- Clean CSS inside <style> tags ---
    for style_tag in soup.find_all("style"):
        if style_tag.string:
            cleaned, img_idx = _clean_css_text(style_tag.string, img_idx, session)
            if cleaned != style_tag.string:
                style_tag.string = cleaned
                stats["css_inline_cleaned"] += 1
                modified = True

    # --- Clean inline style url() ---
    for tag in soup.find_all(style=True):
        style = tag["style"]
        if "url(" in style and ("http" in style or "//" in style):
            _box = [img_idx]

            def _do_replace(m, _b=_box):
                url = m.group(1)
                if _is_remote(url) and "picsum.photos" not in url:
                    placeholder = _picsum_url(_b[0])
                    _b[0] += 1
                    return f"url({placeholder})"
                return m.group(0)

            new_style = re.sub(r'url\(["\']?(https?://[^\s)\"\']+)["\']?\)', _do_replace, style)
            if new_style != style:
                tag["style"] = new_style
                img_idx = _box[0]
                stats["inline_style_cleaned"] += 1
                modified = True

    # --- Clean remote <meta> content (og:image etc.) ---
    for meta in soup.find_all("meta"):
        content = meta.get("content", "")
        if _is_remote(content):
            prop = (meta.get("property") or meta.get("name") or "").lower()
            if "image" in prop:
                meta["content"] = _picsum_url(img_idx)
                img_idx += 1
                modified = True

    # --- Fallback: remaining remote src/poster on other tags ---
    _already_handled = {"img", "source", "input", "script", "link", "video", "audio"}
    for tag in soup.find_all(True):
        if tag.name in _already_handled:
            continue
        for attr in ("src", "poster"):
            val = tag.get(attr, "")
            if val and _is_remote(val) and "picsum.photos" not in val and not _is_safe_domain(val):
                tag[attr] = _picsum_url(img_idx)
                img_idx += 1
                stats["other_replaced"] += 1
                modified = True

    # --- Neutralize external <a> links ---
    local_files = {f.name for f in html_file.parent.glob("*.html")}
    for a in soup.find_all(["a", "area"], href=True):
        href = a["href"]
        if not _is_remote(href):
            continue
        parsed = urlparse(href)
        path = parsed.path.rstrip("/")
        basename = Path(path).name if path else ""
        if basename and basename in local_files:
            a["href"] = basename
        else:
            a["href"] = "#"
        stats["links_neutralized"] += 1
        modified = True

    if modified and not dry_run:
        html_file.write_text(str(soup), encoding="utf-8")

    # 清理本次 soup 的 CSS 尺寸缓存
    _css_dim_cache.pop(id(soup), None)

    return img_idx


# ---------------------------------------------------------------------------
# Main entry: clean entire project
# ---------------------------------------------------------------------------

def clean_project_resources(
    project_dir: Path,
    session=None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """统一资源清洗入口。对项目中所有 HTML/CSS 文件做一次性清理。

    Args:
        project_dir: 项目目录（包含 index.html）
        session: requests.Session，提供则尝试下载 CSS/JS，否则直接删除
        dry_run: 仅统计不修改

    Returns:
        统计结果 dict
    """
    if not project_dir.exists():
        return {"status": "not_found", "project": project_dir.name}

    resources_dir = project_dir / "resources"
    resources_dir.mkdir(exist_ok=True)

    # Delete non-code files from resources/ (images, videos)
    if not dry_run:
        for f in list(resources_dir.iterdir()) if resources_dir.exists() else []:
            if f.is_file() and f.suffix.lower() not in _KEEP_RESOURCE_EXTS:
                f.unlink()

    stats: dict[str, int] = {
        "images_replaced": 0,
        "media_replaced": 0,
        "css_downloaded": 0,
        "css_removed": 0,
        "js_downloaded": 0,
        "js_removed": 0,
        "font_links_removed": 0,
        "tracking_removed": 0,
        "iframes_replaced": 0,
        "links_neutralized": 0,
        "css_inline_cleaned": 0,
        "inline_style_cleaned": 0,
        "other_links_removed": 0,
        "other_replaced": 0,
        "css_files_cleaned": 0,
    }
    img_idx = 0
    html_modified = 0

    # Process all HTML files
    for html_file in sorted(project_dir.glob("*.html")):
        if not html_file.is_file():
            continue
        old_total = sum(stats.values())
        img_idx = _clean_html_file(html_file, resources_dir, session, img_idx, stats, dry_run)
        if sum(stats.values()) > old_total:
            html_modified += 1

    # Process CSS files in resources/
    for css_file in sorted(resources_dir.glob("*.css")) if resources_dir.exists() else []:
        try:
            css_text = css_file.read_text(encoding="utf-8", errors="replace")
            # Step 1: 清理远程 URL
            cleaned, img_idx = _clean_css_text(css_text, img_idx, session)
            # Step 2: 修复断裂的相对路径（../images/ 等）
            cleaned, img_idx = _clean_css_relative_urls(
                cleaned, css_file, project_dir, img_idx, stats, session,
            )
            if cleaned != css_text:
                if not dry_run:
                    css_file.write_text(cleaned, encoding="utf-8")
                stats["css_files_cleaned"] += 1
        except Exception:
            pass

    total = sum(stats.values())
    return {
        "status": "cleaned" if total > 0 else "already_clean",
        "project": project_dir.name,
        "html_modified": html_modified,
        "total_replacements": total,
        **stats,
    }


# ---------------------------------------------------------------------------
# Batch processing: clean all projects in a directory
# ---------------------------------------------------------------------------

def clean_all_projects(
    input_dir: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    """对目录下所有项目（子目录或直接 HTML 文件）做资源清洗。

    兼容两种目录结构：
    1. input_dir/project_name/index.html  (项目级)
    2. input_dir/*.html + input_dir/resources/  (单项目)
    """
    # Check if input_dir itself is a project (has index.html)
    if (input_dir / "index.html").exists():
        result = clean_project_resources(input_dir, dry_run=dry_run)
        _print_stats(result)
        return result

    # Otherwise, treat each subdirectory as a project
    projects = sorted(
        d for d in input_dir.iterdir()
        if d.is_dir() and (d / "index.html").exists()
    )
    if not projects:
        # Fallback: process HTML files directly in the directory
        return _clean_flat_directory(input_dir, dry_run)

    total_stats: dict[str, int] = {}
    modified_projects = 0

    for proj_dir in projects:
        try:
            result = clean_project_resources(proj_dir, dry_run=dry_run)
        except Exception as e:
            print(f"  跳过 {proj_dir.name}: {e}")
            continue
        if result.get("total_replacements", 0) > 0:
            modified_projects += 1
        for k, v in result.items():
            if isinstance(v, int):
                total_stats[k] = total_stats.get(k, 0) + v

    summary = {
        "projects_scanned": len(projects),
        "projects_modified": modified_projects,
        **total_stats,
    }
    return summary


def _clean_flat_directory(input_dir: Path, dry_run: bool) -> dict[str, Any]:
    """Fallback: process HTML/CSS files directly in a directory (no project structure)."""
    html_files = sorted(f for f in input_dir.rglob("*.html") if f.is_file())
    css_files = sorted(f for f in input_dir.rglob("*.css") if f.is_file())
    print(f"找到 {len(html_files)} HTML + {len(css_files)} CSS 文件")

    stats: dict[str, int] = {
        "images_replaced": 0,
        "media_replaced": 0,
        "css_downloaded": 0,
        "css_removed": 0,
        "js_downloaded": 0,
        "js_removed": 0,
        "font_links_removed": 0,
        "tracking_removed": 0,
        "iframes_replaced": 0,
        "links_neutralized": 0,
        "css_inline_cleaned": 0,
        "inline_style_cleaned": 0,
        "other_links_removed": 0,
        "other_replaced": 0,
        "css_files_cleaned": 0,
    }
    img_idx = 0
    html_modified = 0

    for html_file in html_files:
        resources_dir = html_file.parent / "resources"
        old_total = sum(stats.values())
        img_idx = _clean_html_file(html_file, resources_dir, None, img_idx, stats, dry_run)
        if sum(stats.values()) > old_total:
            html_modified += 1

    for css_file in css_files:
        try:
            css_text = css_file.read_text(encoding="utf-8", errors="replace")
            cleaned, img_idx = _clean_css_text(css_text, img_idx)
            if cleaned != css_text:
                if not dry_run:
                    css_file.write_text(cleaned, encoding="utf-8")
                stats["css_files_cleaned"] += 1
        except Exception:
            pass

    return {
        "html_files": len(html_files),
        "css_files": len(css_files),
        "html_modified": html_modified,
        "total_replacements": sum(stats.values()),
        **stats,
    }


def _print_stats(result: dict) -> None:
    """Print human-readable stats."""
    action = "将修改" if result.get("dry_run") else "统计"
    print(f"\n{action}:")
    for k, v in result.items():
        if isinstance(v, int) and v > 0 and k not in ("total_replacements", "html_modified",
                                                         "projects_scanned", "projects_modified",
                                                         "html_files", "css_files"):
            print(f"  {k}: {v}")
    print(f"  总计: {result.get('total_replacements', 0)} 处")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="统一资源清洗：替换远程/缺失资源为 picsum 占位图",
    )
    parser.add_argument("--input-dir", type=Path, required=True,
                        help="项目目录或包含多个项目的父目录")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅统计不修改")
    args = parser.parse_args()

    if not args.input_dir.exists():
        print(f"Error: {args.input_dir} 不存在", file=sys.stderr)
        sys.exit(1)

    result = clean_all_projects(args.input_dir, dry_run=args.dry_run)
    _print_stats(result)

    if args.dry_run:
        print("\n--dry-run 模式，未修改任何文件。")


if __name__ == "__main__":
    main()
