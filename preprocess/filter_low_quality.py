#!/usr/bin/env python3
"""低质量项目过滤器。

扫描数据集目录，识别垃圾页面（域名停放、主机默认页、Cloudflare 拦截等），
将其移入 _rejected/ 子目录（不删除，可恢复）。

用法:
    python3 preprocess/filter_low_quality.py --input-dir datasets/edit_sp --dry-run
    python3 preprocess/filter_low_quality.py --input-dir datasets/edit_sp
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# 阈值
# ---------------------------------------------------------------------------
MIN_HTML_BYTES = 3000      # index.html 最小字节数
MIN_TEXT_CHARS = 200       # 去标签后纯文本最少字符
MIN_DOM_ELEMENTS = 15      # DOM 元素数下限

# ---------------------------------------------------------------------------
# 黑名单关键词（小写匹配）
# 来源：playwright_crawl.py DEAD_PAGE_MARKERS + 扩展多语言
# ---------------------------------------------------------------------------
GARBAGE_PATTERNS: list[str] = [
    # 英文 — 域名停放/主机默认
    "account has been suspended",
    "account suspended",
    "domain is for sale",
    "buy this domain",
    "website is under construction",
    "parked domain",
    "this domain is parked",
    "web hosting default page",
    "apache2 default page",
    "welcome to nginx",
    "expired domain",
    "site not found",
    "no content uploaded",
    "placeholder page",
    "default web page",
    "this page is not available",
    "website coming soon",
    # 英文 — Cloudflare / bot 拦截
    "verify you are human",
    "checking your browser",
    "attention required",
    "just a moment",
    "enable javascript and cookies to continue",
    "performance & security by cloudflare",
    "you have been blocked",
    "please verify you are a human",
    "access denied",
    "sorry, you have been blocked",
    # 荷兰语
    "nog geen website geconfigureerd",
    "webwinkel kan niet worden geladen",
    "webshop kan niet",
    # 葡萄牙语
    "em construção",
    "site em manutenção",
    # 德语
    "diese seite ist nicht verfügbar",
    "noch keine webseite eingerichtet",
    # 主机商品牌
    "contabo",
    "hostinger",
    "godaddy parking",
    "squarespace - claim this domain",
]


def _strip_tags(html: str) -> str:
    """快速去 HTML 标签，返回可见文本。"""
    # 先去 <style> 和 <script> 整块
    text = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def assess_project(project_dir: Path) -> dict:
    """评估单个项目的质量。

    Returns:
        {'verdict': 'keep'|'reject', 'reasons': [...], 'metrics': {...}}
    """
    index = project_dir / "index.html"
    if not index.is_file():
        return {"verdict": "reject", "reasons": ["no index.html"], "metrics": {}}

    html_bytes = index.stat().st_size
    try:
        html = index.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"verdict": "reject", "reasons": [f"read error: {e}"], "metrics": {}}

    visible_text = _strip_tags(html)
    text_chars = len(visible_text)

    soup = BeautifulSoup(html, "html.parser")
    dom_elements = len(soup.find_all(True))

    metrics = {
        "html_bytes": html_bytes,
        "text_chars": text_chars,
        "dom_elements": dom_elements,
    }

    reasons: list[str] = []

    # 规则 1：文件太小且内容太少
    if html_bytes < MIN_HTML_BYTES and text_chars < MIN_TEXT_CHARS:
        reasons.append(f"tiny: {html_bytes}B html, {text_chars} chars text")

    # 规则 2：DOM 太简单且内容太少
    if dom_elements < MIN_DOM_ELEMENTS and text_chars < MIN_TEXT_CHARS:
        reasons.append(f"sparse: {dom_elements} elements, {text_chars} chars text")

    # 规则 3：黑名单关键词
    text_lower = visible_text.lower()
    title_tag = soup.find("title")
    title_lower = (title_tag.get_text().lower() if title_tag else "")
    search_text = text_lower + " " + title_lower

    for pattern in GARBAGE_PATTERNS:
        if pattern in search_text:
            reasons.append(f"blacklist: '{pattern}'")
            break  # 一个就够

    verdict = "reject" if reasons else "keep"
    return {"verdict": verdict, "reasons": reasons, "metrics": metrics}


def filter_dataset(
    dataset_dir: Path,
    dry_run: bool = False,
) -> dict:
    """扫描数据集目录，隔离垃圾项目。

    Returns:
        统计摘要 dict
    """
    rejected_dir = dataset_dir / "_rejected"

    # 收集所有项目目录
    projects = sorted(
        d for d in dataset_dir.iterdir()
        if d.is_dir() and d.name != "_rejected" and (d / "index.html").exists()
    )

    total = len(projects)
    rejected = 0
    kept = 0
    reject_details: list[dict] = []

    for proj in projects:
        result = assess_project(proj)
        if result["verdict"] == "reject":
            rejected += 1
            detail = {
                "project": proj.name,
                "reasons": result["reasons"],
                **result["metrics"],
            }
            reject_details.append(detail)

            if not dry_run:
                dest = rejected_dir / proj.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(proj), str(dest))
        else:
            kept += 1

    summary = {
        "total": total,
        "kept": kept,
        "rejected": rejected,
        "reject_rate": f"{rejected / max(total, 1) * 100:.1f}%",
    }

    # 打印结果
    print(f"\n{'=' * 60}")
    print(f"Dataset: {dataset_dir}")
    print(f"Total: {total}, Kept: {kept}, Rejected: {rejected} ({summary['reject_rate']})")
    if dry_run:
        print("[DRY RUN] No files moved")
    print(f"{'=' * 60}")

    if reject_details:
        print(f"\nRejected projects:")
        for d in reject_details[:30]:  # 最多显示 30 个
            reasons_str = "; ".join(d["reasons"])
            print(f"  {d['project']}: {reasons_str}")
            print(f"    html={d.get('html_bytes', '?')}B, text={d.get('text_chars', '?')} chars, dom={d.get('dom_elements', '?')} elements")
        if len(reject_details) > 30:
            print(f"  ... and {len(reject_details) - 30} more")

    return summary


def main():
    parser = argparse.ArgumentParser(description="过滤低质量/垃圾项目")
    parser.add_argument("--input-dir", type=Path, required=True,
                        help="数据集目录（包含项目子目录）")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅检测，不移动文件")
    args = parser.parse_args()

    if not args.input_dir.is_dir():
        print(f"Error: {args.input_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    filter_dataset(args.input_dir, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
