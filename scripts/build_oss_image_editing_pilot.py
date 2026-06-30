#!/usr/bin/env python3
"""Build a small WebCompass-style image-editing pilot from unified records."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("PW_TEST_SCREENSHOT_NO_FONTS_READY", "1")

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


FONT_FACE_RE = re.compile(r"@font-face\s*{[^}]*}", re.IGNORECASE)
PICSUM_RE = re.compile(r"https?://picsum\.photos/(?:id/(\d+)/)?(\d+)/(\d+)(?:[^\s\"')<>]*)?")
LOCAL_IMAGE_EXT_RE = re.compile(r"\.(?:png|jpe?g|webp|gif|svg|avif)(?:[?#][^\"')<>]*)?$", re.IGNORECASE)
HTML_IMAGE_ATTR_RE = re.compile(r"(?P<prefix>\s(?:src|data-src|data-original|data-lazy-src|data-ll-src)=['\"])(?P<url>[^'\"]+)(?P<suffix>['\"])", re.IGNORECASE)
HTML_SRCSET_RE = re.compile(r"(?P<prefix>\s(?:srcset|data-srcset|data-lazy-srcset)=['\"])(?P<value>[^'\"]+)(?P<suffix>['\"])", re.IGNORECASE)
CSS_URL_RE = re.compile(r"url\((?P<quote>['\"]?)(?P<url>[^)'\"\s]+)(?P=quote)\)", re.IGNORECASE)


def read_jsonl(path: Path, offset: int = 0, limit: int = 0) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for index, line in enumerate(f):
            if index < offset:
                continue
            if limit and len(rows) >= limit:
                break
            rows.append(json.loads(line))
    return rows


def safe_rel(path: str) -> Path:
    rel = Path(path)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"unsafe path: {path}")
    return rel


def write_files(root: Path, files: list[dict[str, str]]) -> None:
    for item in files:
        dest = root / safe_rel(item["path"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        code = item["code"]
        if dest.suffix.lower() in {".html", ".htm", ".css"}:
            code = FONT_FACE_RE.sub("", code)
        dest.write_text(code, encoding="utf-8")


def stable_lock(value: str) -> int:
    h = 0
    for ch in value or "missing-image":
        h = ((h * 31) + ord(ch)) & 0xFFFFFFFF
    return h % 100000


def loremflickr_url(width: int, height: int, seed: str) -> str:
    width = max(1, int(width or 300))
    height = max(1, int(height or 200))
    return f"https://loremflickr.com/{width}/{height}?lock={stable_lock(seed)}"


def parse_size_from_url(url: str) -> tuple[int, int]:
    match = re.search(r"/(\d{2,4})/(\d{2,4})(?:[/?#]|$)", url)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r"[-_](\d{2,4})x(\d{2,4})(?:[._/?#]|$)", url)
    if match:
        return int(match.group(1)), int(match.group(2))
    return 300, 200


def is_local_image_url(url: str) -> bool:
    text = (url or "").strip()
    if not text or text.lower() == "null" or text.startswith("#"):
        return True
    if re.match(r"^(?:https?:|data:|blob:)", text, re.IGNORECASE):
        return False
    return bool(LOCAL_IMAGE_EXT_RE.search(text)) or text.startswith(("/", "./", "../"))


def rewrite_srcset_value(value: str) -> str:
    rewritten: list[str] = []
    for candidate in value.split(","):
        parts = candidate.strip().split()
        if not parts:
            continue
        url = parts[0]
        descriptor = " ".join(parts[1:])
        new_url = rewrite_image_url(url)
        rewritten.append(" ".join(part for part in [new_url, descriptor] if part))
    return ", ".join(rewritten)


def rewrite_image_url(url: str) -> str:
    text = (url or "").strip()
    picsum = PICSUM_RE.match(text)
    if picsum:
        image_id, width, height = picsum.groups()
        return loremflickr_url(int(width), int(height), image_id or text)
    if is_local_image_url(text):
        width, height = parse_size_from_url(text)
        return loremflickr_url(width, height, text)
    return text


def persist_image_replacements(code: str) -> str:
    def replace_attr(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}{rewrite_image_url(match.group('url'))}{match.group('suffix')}"

    def replace_srcset(match: re.Match[str]) -> str:
        return f"{match.group('prefix')}{rewrite_srcset_value(match.group('value'))}{match.group('suffix')}"

    def replace_css(match: re.Match[str]) -> str:
        url = rewrite_image_url(match.group("url"))
        quote = match.group("quote") or ""
        return f"url({quote}{url}{quote})"

    code = PICSUM_RE.sub(lambda match: loremflickr_url(int(match.group(2)), int(match.group(3)), match.group(1) or match.group(0)), code)
    code = HTML_IMAGE_ATTR_RE.sub(replace_attr, code)
    code = HTML_SRCSET_RE.sub(replace_srcset, code)
    code = CSS_URL_RE.sub(replace_css, code)
    return code


def normalize_files_for_render(files: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in files:
        code = item["code"]
        suffix = Path(item["path"]).suffix.lower()
        if suffix in {".html", ".htm", ".css"}:
            code = FONT_FACE_RE.sub("", persist_image_replacements(code))
        normalized.append({"path": item["path"], "code": code})
    return normalized


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def force_lazy_images_script() -> str:
    return """
    async () => {
      const invalidImageValue = value => {
        if (value === null || value === undefined) return true;
        const text = String(value).trim();
        return text === '' || text.toLowerCase() === 'null' || text.startsWith('#');
      };
      const isLocalImageRef = value => {
        if (invalidImageValue(value)) return false;
        const text = String(value).trim();
        return !/^(https?:|data:|blob:)/i.test(text);
      };
      const srcsetIsInvalidOrLocal = value => {
        if (invalidImageValue(value)) return true;
        return String(value).split(',').every(candidate => {
          const url = candidate.trim().split(/\\s+/)[0];
          return invalidImageValue(url) || isLocalImageRef(url);
        });
      };
      const hashLock = value => {
        value = String(value || 'missing-image');
        let hash = 0;
        for (let i = 0; i < value.length; i++) hash = ((hash * 31) + value.charCodeAt(i)) >>> 0;
        return hash % 100000;
      };
      const replacementUrl = (img, value) => {
        const width = Math.max(1, Math.round(Number(img.getAttribute('width')) || img.clientWidth || 300));
        const height = Math.max(1, Math.round(Number(img.getAttribute('height')) || img.clientHeight || 200));
        return `https://loremflickr.com/${width}/${height}?lock=${hashLock(value)}`;
      };
      const repairPictureSources = () => {
        document.querySelectorAll('picture source').forEach(source => {
          const srcset = source.getAttribute('srcset');
          if (srcsetIsInvalidOrLocal(srcset)) source.remove();
        });
        document.querySelectorAll('img').forEach(img => {
          const srcset = img.getAttribute('srcset');
          if (srcsetIsInvalidOrLocal(srcset)) img.removeAttribute('srcset');
          const attrSrc = img.getAttribute('src');
          if (invalidImageValue(attrSrc) || isLocalImageRef(attrSrc)) {
            img.src = replacementUrl(img, attrSrc || img.outerHTML || 'missing-image');
            return;
          }
          if (attrSrc && !invalidImageValue(attrSrc) && /\\/null(?:$|[?#])/.test(img.currentSrc || '')) {
            img.src = attrSrc;
          }
        });
      };
      const stripFontFaces = () => {
        document.querySelectorAll('style').forEach(style => {
          style.textContent = style.textContent.replace(/@font-face\\s*{[^}]*}/gi, '');
        });
        for (const sheet of [...document.styleSheets]) {
          try {
            for (let i = sheet.cssRules.length - 1; i >= 0; i--) {
              const rule = sheet.cssRules[i];
              if (rule && rule.type === CSSRule.FONT_FACE_RULE) sheet.deleteRule(i);
            }
          } catch (error) {}
        }
      };
      stripFontFaces();
      repairPictureSources();
      document.querySelectorAll('img').forEach(img => {
        img.loading = 'eager';
        for (const [attr, target] of [
          ['data-src', 'src'],
          ['data-original', 'src'],
          ['data-lazy-src', 'src'],
          ['data-ll-src', 'src'],
          ['data-srcset', 'srcset'],
          ['data-lazy-srcset', 'srcset']
        ]) {
          const value = img.getAttribute(attr);
          if (value) img.setAttribute(target, value);
        }
      });
      for (let y = 0; y <= document.body.scrollHeight; y += 700) {
        window.scrollTo(0, y);
        window.dispatchEvent(new Event('scroll'));
        await new Promise(resolve => setTimeout(resolve, 120));
      }
      window.scrollTo(0, 0);
      await Promise.race([
        Promise.all([...document.images].map(img => img.complete ? true : new Promise(resolve => { img.onload = img.onerror = resolve; }))),
        new Promise(resolve => setTimeout(resolve, 8000))
      ]);
      stripFontFaces();
      repairPictureSources();
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    """


def protect_image_sources_script() -> str:
    return """
    (() => {
      const invalid = value => {
        if (value === null || value === undefined) return true;
        const text = String(value).trim();
        return text === '' || text.toLowerCase() === 'null' || text.startsWith('#');
      };
      const nativeSetAttribute = Element.prototype.setAttribute;
      Element.prototype.setAttribute = function(name, value) {
        const attr = String(name || '').toLowerCase();
        const tag = String(this.tagName || '').toLowerCase();
        if ((tag === 'img' && attr === 'src' || tag === 'source' && attr === 'srcset') && invalid(value)) return;
        return nativeSetAttribute.call(this, name, value);
      };
      const imgSrc = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src');
      if (imgSrc && imgSrc.set) {
        Object.defineProperty(HTMLImageElement.prototype, 'src', {
          get: imgSrc.get,
          set(value) {
            if (invalid(value)) return;
            return imgSrc.set.call(this, value);
          },
          configurable: true,
          enumerable: imgSrc.enumerable
        });
      }
      const sourceSrcset = Object.getOwnPropertyDescriptor(HTMLSourceElement.prototype, 'srcset');
      if (sourceSrcset && sourceSrcset.set) {
        Object.defineProperty(HTMLSourceElement.prototype, 'srcset', {
          get: sourceSrcset.get,
          set(value) {
            if (invalid(value)) return;
            return sourceSrcset.set.call(this, value);
          },
          configurable: true,
          enumerable: sourceSrcset.enumerable
        });
      }
    })();
    """


def image_stats_script() -> str:
    return """
    () => {
      const images = [...document.images];
      const loadable = images.filter(img => img.getAttribute('src') || img.getAttribute('srcset'));
      const visible = images.filter(img => img.clientWidth > 0 && img.clientHeight > 0);
      const visibleLoadable = visible.filter(img => img.getAttribute('src') || img.getAttribute('srcset'));
      return {
        image_count: images.length,
        loaded_image_count: images.filter(img => img.naturalWidth > 0).length,
        loadable_image_count: loadable.length,
        loaded_loadable_image_count: loadable.filter(img => img.naturalWidth > 0).length,
        visible_image_count: visible.length,
        visible_loadable_image_count: visibleLoadable.length,
        loaded_visible_loadable_image_count: visibleLoadable.filter(img => img.naturalWidth > 0).length
      };
    }
    """


def wait_for_image_progress(page, max_wait_ms: int = 20000, stable_rounds: int = 4) -> dict[str, int]:
    """Wait until image loading stops making visible progress, then return stats."""
    deadline = time.monotonic() + max_wait_ms / 1000
    last_loaded = -1
    stable = 0
    try:
        stats = page.evaluate(image_stats_script())
    except PlaywrightError:
        return {
            "image_count": 0,
            "loaded_image_count": 0,
            "loadable_image_count": 0,
            "loaded_loadable_image_count": 0,
            "visible_image_count": 0,
            "visible_loadable_image_count": 0,
            "loaded_visible_loadable_image_count": 0,
        }
    while time.monotonic() < deadline:
        remaining = stats["loadable_image_count"] - stats["loaded_loadable_image_count"]
        if remaining <= 0:
            return stats
        page.wait_for_timeout(1000)
        try:
            stats = page.evaluate(image_stats_script())
        except PlaywrightError:
            break
        loaded = stats["loaded_loadable_image_count"]
        if loaded <= last_loaded:
            stable += 1
        else:
            stable = 0
            last_loaded = loaded
        if stable >= stable_rounds:
            break
    return stats


def screenshot_index(project_dir: Path, out_dir: Path, proxy_server: str | None = None) -> tuple[str, dict[str, int]]:
    html = project_dir / "index.html"
    if not html.exists():
        raise FileNotFoundError(f"missing index.html in {project_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / "screenshot_index.jpg"
    port = free_port()
    server = subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=str(project_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    with sync_playwright() as p:
        launch_kwargs: dict[str, Any] = {"headless": True}
        if proxy_server:
            launch_kwargs["proxy"] = {
                "server": proxy_server,
                "bypass": "127.0.0.1,localhost",
            }
        browser = p.chromium.launch(**launch_kwargs)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.add_init_script(protect_image_sources_script())
        page.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type == "font"
            else route.continue_(),
        )
        try:
            time.sleep(0.5)
            url = f"http://127.0.0.1:{port}/index.html"
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except PlaywrightTimeoutError:
                page.goto(url, wait_until="commit", timeout=15000)
            page.wait_for_timeout(1500)
            try:
                page.wait_for_selector("body", timeout=5000)
            except PlaywrightTimeoutError:
                pass
            try:
                page.evaluate(force_lazy_images_script())
            except PlaywrightError:
                pass
            try:
                page.add_style_tag(
                    content="""
                    *, *::before, *::after {
                      animation: none !important;
                      transition: none !important;
                    }
                    """
                )
            except Exception:
                pass
            image_stats = wait_for_image_progress(page)
            try:
                page.screenshot(path=str(dest), full_page=True, type="jpeg", quality=82, timeout=90000)
            except PlaywrightError:
                page.screenshot(path=str(dest), full_page=False, type="jpeg", quality=82, timeout=30000)
        finally:
            try:
                page.close()
            finally:
                browser.close()
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
    return dest.name, image_stats


def build_info(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "instance_id": record["instance_id"],
        "task": "edit",
        "task_type": record.get("task_type", []),
        "page_type": record.get("page_type", "sp"),
        "description": [
            {"task_type": task_type, "description": record.get("instruction", "")}
            for task_type in (record.get("task_type") or ["Editing"])
        ],
        "src_code": record["input_files"],
        "dst_code": [],
        "src_screenshot": ["screenshot_index.jpg"],
        "dst_screenshot": [],
        "label_modified_files": record["patches"],
        "resources": record.get("resources", []),
        "meta": {
            "source_schema": record.get("source_schema"),
            "source_instance_id": record.get("instance_id"),
            "screenshot_viewport": {"width": 1920, "height": 1080, "full_page": True},
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--proxy-server", default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.out_dir.exists() and args.overwrite:
        shutil.rmtree(args.out_dir)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = args.out_dir / "manifest_image_editing_pilot.jsonl"
    if manifest_path.exists() and args.overwrite:
        manifest_path.unlink()

    records = read_jsonl(args.input_jsonl, offset=args.offset, limit=args.limit)
    ok = 0
    failed = 0
    for idx, record in enumerate(records, start=1):
        instance_dir = args.out_dir / "sp" / record["instance_id"]
        try:
            if instance_dir.exists():
                if not args.overwrite:
                    continue
                shutil.rmtree(instance_dir)
            src_dir = instance_dir / "src"
            shot_dir = instance_dir / "src_screenshots"
            write_files(src_dir, record["input_files"])
            _, image_stats = screenshot_index(src_dir, shot_dir, proxy_server=args.proxy_server)
            (instance_dir / "info.json").write_text(
                json.dumps(build_info(record), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            payload = {
                "index": idx,
                "instance_id": record["instance_id"],
                "status": "ok",
                "src_screenshot": "src_screenshots/screenshot_index.jpg",
                "patch_count": len(record.get("patches", [])),
                "image_stats": image_stats,
            }
            ok += 1
        except Exception as exc:  # noqa: BLE001
            shutil.rmtree(instance_dir, ignore_errors=True)
            payload = {
                "index": idx,
                "instance_id": record.get("instance_id"),
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }
            failed += 1
        with manifest_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    summary = {
        "input_jsonl": str(args.input_jsonl),
        "limit": args.limit,
        "proxy_server": args.proxy_server,
        "ok": ok,
        "failed": failed,
    }
    (args.out_dir / "_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
