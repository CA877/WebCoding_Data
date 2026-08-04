"""从 WebCode2M 下载 N 个 case 到本地 inspect_entries/ 目录。"""
from __future__ import annotations

import os
import re
import sys
import json
import shutil
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

OUT_DIR = Path(__file__).resolve().parent / "inspect_video_gen"
NUM_CASES = 30
START_OFFSET = 0  # WebCode2M 起始 offset

HF_DATASET = "xcodemind/webcode2m"
API_URL = f"https://datasets-server.huggingface.co/rows?dataset={HF_DATASET}&config=default&split=train"

# 资源文件扩展名（只下载这些）
RESOURCE_EXTS = {".css", ".js", ".jsx", ".ts", ".tsx", ".woff", ".woff2", ".ttf", ".otf"}
CSS_URL_RE = re.compile(r'url\(["\']?([^)"\']+)["\']?\)', re.I)
SRC_HREF_RE = re.compile(r'''(?:src|href)=["']([^"']+)["']''', re.I)
RESOURCE_PATH_RE = re.compile(r'["\']([^"\']+(?:\\/[^"\']*)?)["\']', re.I)


def fetch_rows(offset: int, length: int) -> list[dict]:
    url = f"{API_URL}&offset={offset}&length={length}"
    with httpx.Client(timeout=120, verify=False) as client:
        resp = client.get(url)
        resp.raise_for_status()
        data = resp.json()
    if "rows" not in data:
        raise RuntimeError(f"Unexpected API response: {json.dumps(data)[:500]}")
    return [r["row"] for r in data["rows"]]


def extract_resource_urls(html: str, base_url: str) -> list[str]:
    """从 HTML 中提取引用的 CSS/JS 资源 URL。"""
    urls = set()
    for pattern in [SRC_HREF_RE]:
        for m in pattern.finditer(html):
            url = m.group(1)
            parsed = urlparse(url)
            if parsed.scheme in ("", "http", "https"):
                # 只保留 CSS/JS/字体
                ext = Path(parsed.path).suffix.lower()
                if ext in RESOURCE_EXTS:
                    if parsed.netloc:
                        urls.add(url)
                    else:
                        urls.add(urljoin(base_url, url))
    # 同时也从 CSS url() 中提取
    for m in CSS_URL_RE.finditer(html):
        url = m.group(1)
        ext = Path(urlparse(url).path).suffix.lower()
        if ext in RESOURCE_EXTS:
            if urlparse(url).netloc:
                urls.add(url)
            else:
                urls.add(urljoin(base_url, url))
    return list(urls)


def safe_filename(url: str) -> str:
    """从 URL 生成安全的文件名。"""
    import hashlib
    parsed = urlparse(url)
    path_parts = parsed.path.strip("/").split("/")
    name = path_parts[-1] if path_parts else "resource"
    # 保留扩展名，前面加 hash 防冲突
    h = hashlib.md5(url.encode()).hexdigest()[:8]
    stem = Path(name).stem or "resource"
    ext = Path(name).suffix or ".txt"
    return f"{h}_{stem}{ext}"


def process_case(row: dict, idx: int, dst_dir: Path) -> bool:
    """下载并保存一个 case。返回是否有效。"""
    html = row.get("text", "")
    if not html or len(html) < 500:
        print(f"  [{idx}] 跳过：HTML 太短 ({len(html)} 字符)")
        return False

    # 跳过 RSS/XML feed
    if re.search(r'<(rss|feed|channel)\b', html, re.I) and "<html" not in html[:500].lower():
        print(f"  [{idx}] 跳过：疑似 RSS/XML feed")
        return False

    # 从 HTML 中提取 <title>
    title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).strip()[:100] if title_match else "no_title"
    print(f"  [{idx}] {title}  (HTML {len(html):,} 字符)")

    # 创建输出目录
    case_dir = dst_dir / f"case_{idx:03d}"
    case_dir.mkdir(parents=True, exist_ok=True)

    # 保存 metadata
    meta = {
        "idx": idx,
        "title": title,
        "url": row.get("url", ""),
        "lang": row.get("lang", ""),
        "html_length": len(html),
        "score": row.get("score", 0),
        "hash": row.get("hash", ""),
        "tokens": row.get("tokens", ""),
        "scale": row.get("scale", []),
    }
    (case_dir / "info.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    # 保存 HTML
    (case_dir / "index.html").write_text(html, encoding="utf-8")

    # 下载 screenshot
    img_info = row.get("image", {})
    img_url = img_info.get("src", "") if isinstance(img_info, dict) else ""
    if img_url:
        try:
            with httpx.Client(timeout=60, verify=False) as client:
                resp = client.get(img_url)
                if resp.status_code == 200:
                    (case_dir / "screenshot.png").write_bytes(resp.content)
                    print(f"    screenshot: {len(resp.content):,} bytes")
                else:
                    print(f"    screenshot 下载失败: HTTP {resp.status_code}")
        except Exception as e:
            print(f"    screenshot 下载失败: {e}")

    # 提取并下载资源
    base_url = row.get("url", "https://example.com/")
    if not base_url.startswith("http"):
        base_url = "https://example.com/"

    resource_urls = extract_resource_urls(html, base_url)
    if resource_urls:
        resources_dir = case_dir / "resources"
        resources_dir.mkdir(exist_ok=True)
        for rurl in resource_urls[:20]:  # 每个 case 最多 20 个资源
            try:
                fname = safe_filename(rurl)
                with httpx.Client(timeout=30, verify=False, follow_redirects=True) as client:
                    resp = client.get(rurl)
                    if resp.status_code == 200 and len(resp.content) > 0:
                        (resources_dir / fname).write_bytes(resp.content)
            except Exception:
                pass  # 资源下载失败不影响整体

    return True


def main():
    offset = int(os.environ.get("OFFSET", START_OFFSET))
    num = int(os.environ.get("NUM", NUM_CASES))

    print(f"从 {HF_DATASET} offset={offset} 下载 {num} 个 case...")
    print(f"输出目录: {OUT_DIR}")
    print()

    # 清理旧输出
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)

    # 多取一些以应对坏 case (RSS feed 等)
    fetch_count = num * 2
    rows = fetch_rows(offset, fetch_count)
    print(f"获取到 {len(rows)} 条记录\n")

    saved = 0
    for i, row in enumerate(rows):
        if saved >= num:
            break
        ok = process_case(row, offset + i, OUT_DIR)
        if ok:
            saved += 1
        print(f"    进度: {saved}/{num}")

    print(f"\n完成！{saved} 个 case 保存在 {OUT_DIR}/")
    # 列出所有 case
    for d in sorted(OUT_DIR.iterdir()):
        if d.is_dir():
            files = list(d.rglob("*"))
            html = d / "index.html"
            title = ""
            if html.exists():
                m = re.search(r"<title>(.*?)</title>", html.read_text("utf-8", errors="ignore"), re.I | re.DOTALL)
                title = m.group(1).strip()[:80] if m else ""
            print(f"  {d.name}: {title}  ({len(files)} files)")


if __name__ == "__main__":
    main()
