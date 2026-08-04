#!/usr/bin/env python3
"""
将 HTML 中已删除的本地图片引用替换为 picsum.photos 占位图 URL。

用法:
    python3 scripts/replace_local_images.py \
        --input-dir /path/to/generate_sp/sp \
        --dry-run          # 预览

    python3 scripts/replace_local_images.py \
        --input-dir /path/to/generate_sp/sp   # 原地替换
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

# 图片后缀
IMG_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".ico"}

# 根据文件名关键词猜测尺寸
SIZE_HINTS = [
    (r"logo|icon|favicon", (120, 60)),
    (r"banner|hero|slide|cover|bg|background", (1200, 600)),
    (r"thumb|avatar|profile", (150, 150)),
]
DEFAULT_SIZE = (400, 300)


def guess_size_from_name(filename: str) -> tuple[int, int]:
    name = filename.lower()
    for pattern, size in SIZE_HINTS:
        if re.search(pattern, name):
            return size
    return DEFAULT_SIZE


def picsum_url(seed: str, width: int, height: int) -> str:
    """生成基于 seed 的确定性 picsum URL。"""
    # 用 hash 的前 4 位做 seed，保证同一文件名每次替换结果一致
    h = int(hashlib.md5(seed.encode()).hexdigest()[:4], 16) % 1000
    return f"https://picsum.photos/seed/{h}/{width}/{height}"


# 匹配 <img> 标签中的本地图片 src
IMG_TAG_RE = re.compile(
    r'(<img\b[^>]*?\bsrc\s*=\s*["\'])(\./)?resources/([^"\'>\s]+\.(jpg|jpeg|png|gif|webp|bmp|ico))(["\'][^>]*?>)',
    re.IGNORECASE,
)

# 匹配 CSS url() 中的本地图片
CSS_URL_RE = re.compile(
    r'(url\s*\(\s*["\']?)(\./)?resources/([^"\')\s]+\.(jpg|jpeg|png|gif|webp|bmp|ico))(["\']?\s*\))',
    re.IGNORECASE,
)

# 从 img 标签提取 width/height
WH_RE = re.compile(r'\b(width|height)\s*=\s*["\']?(\d+)', re.IGNORECASE)


def extract_img_dimensions(tag: str) -> tuple[int | None, int | None]:
    dims = {}
    for m in WH_RE.finditer(tag):
        dims[m.group(1).lower()] = int(m.group(2))
    return dims.get("width"), dims.get("height")


def replace_in_img_tag(match: re.Match) -> str:
    prefix = match.group(1)       # <img ... src="
    filename = match.group(3)     # resources/xxx.jpg 中的 xxx.jpg
    suffix = match.group(5)       # " ... >

    full_tag = match.group(0)
    w, h = extract_img_dimensions(full_tag)

    if w is None or h is None:
        gw, gh = guess_size_from_name(filename)
        w = w or gw
        h = h or gh

    url = picsum_url(filename, w, h)
    return f"{prefix}{url}{suffix}"


def replace_in_css_url(match: re.Match) -> str:
    prefix = match.group(1)
    filename = match.group(3)
    suffix = match.group(5)

    w, h = guess_size_from_name(filename)
    url = picsum_url(filename, w, h)
    return f"{prefix}{url}{suffix}"


def process_file(html_path: Path, dry_run: bool = False) -> int:
    content = html_path.read_text(encoding="utf-8", errors="replace")

    new_content, n1 = IMG_TAG_RE.subn(replace_in_img_tag, content)
    new_content, n2 = CSS_URL_RE.subn(replace_in_css_url, new_content)
    total = n1 + n2

    if total > 0 and not dry_run:
        html_path.write_text(new_content, encoding="utf-8")

    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Replace local image refs with picsum.photos URLs")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.input_dir.exists():
        print(f"Error: 目录不存在: {args.input_dir}", file=sys.stderr)
        sys.exit(1)

    html_files = sorted(f for f in args.input_dir.rglob("*.html") if f.is_file())
    print(f"找到 {len(html_files)} 个 HTML 文件")

    total_replaced = 0
    files_modified = 0

    for html_path in html_files:
        n = process_file(html_path, dry_run=args.dry_run)
        if n > 0:
            total_replaced += n
            files_modified += 1

    action = "将替换" if args.dry_run else "已替换"
    print(f"{action} {total_replaced} 处图片引用（{files_modified} 个文件）")
    if args.dry_run:
        print("--dry-run 模式，未修改任何文件。")


if __name__ == "__main__":
    main()
