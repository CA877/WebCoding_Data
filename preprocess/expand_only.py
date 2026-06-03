#!/usr/bin/env python3
"""纯多页扩展：从 useful/ 读取单页项目，爬取子页面，输出到 useful_mp/

不下载任何资源（图片/CSS/JS），不清理，保留原始链接。
"""

import argparse
import json
import re
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

# 项目根路径
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "preprocess"))

from playwright.sync_api import sync_playwright
from playwright_crawl import (
    build_requests_session,
    extract_nav_links,
    safe_filename,
    snapshot_page,
    validate_page,
)


def expand_to_multi(project_dir: Path, output_dir: Path,
                    browser_proxy: str = "", requests_proxy: str = "",
                    max_pages: int = 5) -> dict[str, Any]:
    """纯 HTML expand：找到子页面，下载 HTML，不碰资源。

    输出结构：
        useful_mp/{project}/
        ├── index.html          # 原始单页
        ├── page_1.html         # 子页面 1
        ├── page_2.html         # 子页面 2
        └── expand_result.json  # 元数据
    """
    index_html = project_dir / "index.html"
    if not index_html.exists():
        return {"status": "no_index", "project": project_dir.name}

    html = index_html.read_text(encoding="utf-8", errors="replace")

    # 提取域名
    all_urls = re.findall(r'https?://([^/\s"\'<>]+)', html)
    noise = {"google", "facebook", "twitter", "cdn", "fonts.g", "jquery",
             "bootstrap", "cloudflare", "gstatic", "w3.org", "schema.org",
             "gravatar", "youtube", "vimeo", "instagram", "linkedin",
             "pinterest", "googletagmanager", "doubleclick", "fontawesome"}
    real_domains = [d for d in all_urls if not any(n in d.lower() for n in noise)]

    if not real_domains:
        return {"status": "no_domain", "project": project_dir.name}

    main_domain = Counter(real_domains).most_common(1)[0][0]
    base_url = f"https://{main_domain}/"

    # 找 nav links
    nav_links = extract_nav_links(html, base_url, max_links=max_pages)
    if not nav_links:
        return {"status": "no_nav_links", "project": project_dir.name, "domain": main_domain}

    # 创建输出目录，复制 index.html
    out = output_dir / project_dir.name
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(index_html, out / "index.html")

    session = build_requests_session(requests_proxy)

    pages_added = 0
    total_fails = 0
    used_names: set[str] = {"index.html"}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            proxy={"server": browser_proxy} if browser_proxy else None,
            headless=True,
        )
        page = browser.new_page(viewport={"width": 1280, "height": 800})

        for i, sub_url in enumerate(nav_links):
            sub_html = snapshot_page(page, sub_url, wait_ms=3000)
            if not sub_html:
                total_fails += 1
                if total_fails >= 3:
                    break
                continue
            if not validate_page(sub_html):
                total_fails += 1
                if total_fails >= 3:
                    break
                continue

            pages_added += 1
            filename = safe_filename(sub_url, i + 1, used_names)
            (out / filename).write_text(sub_html, encoding="utf-8")
            print(f"    [{pages_added}] {filename} ({len(sub_html)} bytes)")

            if pages_added >= max_pages:
                break

        page.close()
        browser.close()

    return {
        "status": "expanded" if pages_added > 0 else "crawl_failed",
        "project": project_dir.name,
        "domain": main_domain,
        "nav_links_found": len(nav_links),
        "pages_added": pages_added,
        "total_fails": total_fails,
    }


def _process_one(payload):
    """Module-level function for ProcessPoolExecutor (must be picklable)."""
    proj, output_dir, browser_proxy, requests_proxy, max_pages, manifest_path = payload
    t0 = time.time()
    try:
        result = expand_to_multi(proj, output_dir,
                                 browser_proxy=browser_proxy,
                                 requests_proxy=requests_proxy,
                                 max_pages=max_pages)
    except Exception as exc:
        result = {"status": "error", "project": proj.name, "error": str(exc)}
    result["elapsed"] = round(time.time() - t0, 1)

    line = json.dumps(result, ensure_ascii=False) + "\n"
    with manifest_path.open("a") as f:
        f.write(line)

    tag = f"+{result.get('pages_added',0)}页" if result["status"] == "expanded" else result["status"]
    print(f"  {proj.name}: {tag} {result['elapsed']}s", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description="纯多页扩展 — 只爬 HTML，不下载资源")
    parser.add_argument("--input-dir", type=Path, required=True,
                        help="输入目录 (useful/)")
    parser.add_argument("--output-dir", type=Path, required=True,
                        help="输出目录 (useful_mp/)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--browser-proxy", default="")
    parser.add_argument("--requests-proxy", default="")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output_dir / "expand_results.jsonl"

    projects = sorted(
        d for d in args.input_dir.iterdir()
        if d.is_dir() and (d / "index.html").exists()
    )
    if args.limit:
        projects = projects[:args.limit]

    # 续跑
    done = set()
    if manifest_path.exists():
        for line in manifest_path.read_text().splitlines():
            try:
                e = json.loads(line)
                done.add(e.get("project", ""))
            except json.JSONDecodeError:
                pass

    pending = [p for p in projects if p.name not in done]
    print(f"输入: {len(projects)} 项目, 已完成: {len(done)}, 待处理: {len(pending)}")

    from concurrent.futures import ProcessPoolExecutor, as_completed

    payloads = [
        (proj, args.output_dir, args.browser_proxy, args.requests_proxy, args.max_pages, manifest_path)
        for proj in pending
    ]

    results = []
    expanded = 0
    failed = 0

    with ProcessPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {executor.submit(_process_one, p): p for p in payloads}
        for i, future in enumerate(as_completed(futures)):
            result = future.result()
            results.append(result)
            if result["status"] == "expanded":
                expanded += 1
            else:
                failed += 1
            print(f"[{i+1}/{len(pending)}] ok={expanded} fail={failed}", flush=True)

    print(f"\n完成: {len(results)} 处理, 成功={expanded}, 失败={failed}")
    print(f"输出: {args.output_dir}")


if __name__ == "__main__":
    main()
