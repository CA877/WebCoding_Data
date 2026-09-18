#!/usr/bin/env python3
"""Diagnose local HTML rendering for a few unified WebCoding records."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

os.environ.setdefault("PW_TEST_SCREENSHOT_NO_FONTS_READY", "1")

from playwright.sync_api import Route, sync_playwright


FONT_FACE_RE = re.compile(r"@font-face\s*{[^}]*}", re.IGNORECASE)


def read_records(path: Path, offset: int, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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
    root.mkdir(parents=True, exist_ok=True)
    for item in files:
        dest = root / safe_rel(item["path"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        code = item["code"]
        if dest.suffix.lower() in {".html", ".htm", ".css"}:
            code = FONT_FACE_RE.sub("", code)
        dest.write_text(code, encoding="utf-8")


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def lazy_script() -> str:
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
            img.src = replacementUrl(img, attrSrc);
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
        img.decoding = 'sync';
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
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      window.scrollTo(0, 0);
      await Promise.race([
        Promise.all([...document.images].map(img => img.complete ? true : new Promise(resolve => { img.onload = img.onerror = resolve; }))),
        new Promise(resolve => setTimeout(resolve, 10000))
      ]);
      stripFontFaces();
      repairPictureSources();
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    """


def image_table_script() -> str:
    return """
    () => [...document.images].map((img, index) => ({
      index,
      src: img.currentSrc || img.src || '',
      attr_src: img.getAttribute('src') || '',
      srcset: img.getAttribute('srcset') || '',
      loading: img.getAttribute('loading') || '',
      complete: img.complete,
      naturalWidth: img.naturalWidth,
      naturalHeight: img.naturalHeight,
      clientWidth: img.clientWidth,
      clientHeight: img.clientHeight,
      alt: img.getAttribute('alt') || ''
    }))
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


def log_stage(out_dir: Path, message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    print(line, flush=True)
    with (out_dir / "stages.log").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def render_case(project_dir: Path, out_dir: Path, timeout_ms: int) -> dict[str, Any]:
    html = project_dir / "index.html"
    if not html.exists():
        raise FileNotFoundError(f"missing index.html: {project_dir}")

    port = free_port()
    server = subprocess.Popen(
        ["python3", "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=str(project_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    events: list[dict[str, Any]] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = out_dir / "screenshot.jpg"

    def route_handler(route: Route) -> None:
        req = route.request
        if req.resource_type == "font":
            events.append({"kind": "abort_font", "url": req.url})
            route.abort()
            return
        route.continue_()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1920, "height": 1080})
            page.add_init_script(protect_image_sources_script())
            page.route("**/*", route_handler)
            page.on(
                "requestfailed",
                lambda req: events.append(
                    {
                        "kind": "requestfailed",
                        "type": req.resource_type,
                        "url": req.url,
                        "failure": req.failure,
                    }
                ),
            )
            page.on(
                "response",
                lambda resp: events.append(
                    {
                        "kind": "response",
                        "type": resp.request.resource_type,
                        "url": resp.url,
                        "status": resp.status,
                    }
                )
                if resp.request.resource_type in {"image", "stylesheet", "script", "document"}
                else None,
            )
            try:
                log_stage(out_dir, "goto:start")
                page.goto(f"http://127.0.0.1:{port}/index.html", wait_until="domcontentloaded", timeout=timeout_ms)
                log_stage(out_dir, "goto:done")
                page.wait_for_timeout(1500)
                log_stage(out_dir, "lazy:start")
                page.evaluate(lazy_script())
                log_stage(out_dir, "lazy:done")
                page.add_style_tag(
                    content="""
                    *, *::before, *::after {
                      animation: none !important;
                      transition: none !important;
                    }
                    """
                )
                log_stage(out_dir, "image_table:start")
                images = page.evaluate(image_table_script())
                log_stage(out_dir, f"image_table:done {sum(1 for img in images if img.get('naturalWidth', 0) > 0)}/{len(images)}")
                log_stage(out_dir, "screenshot:start")
                page.screenshot(path=str(screenshot_path), full_page=True, type="jpeg", quality=82, timeout=timeout_ms)
                log_stage(out_dir, "screenshot:done")
            finally:
                page.close()
                browser.close()
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()

    loadable_images = [img for img in images if img.get("attr_src") or img.get("srcset")]
    visible_images = [img for img in images if img.get("clientWidth", 0) > 0 and img.get("clientHeight", 0) > 0]
    visible_loadable_images = [img for img in visible_images if img.get("attr_src") or img.get("srcset")]
    image_events = [e for e in events if e.get("type") == "image" or e.get("kind") == "requestfailed"]
    summary = {
        "screenshot": str(screenshot_path),
        "image_count": len(images),
        "loaded_image_count": sum(1 for img in images if img.get("naturalWidth", 0) > 0),
        "loadable_image_count": len(loadable_images),
        "loaded_loadable_image_count": sum(1 for img in loadable_images if img.get("naturalWidth", 0) > 0),
        "visible_image_count": len(visible_images),
        "visible_loadable_image_count": len(visible_loadable_images),
        "loaded_visible_loadable_image_count": sum(
            1 for img in visible_loadable_images if img.get("naturalWidth", 0) > 0
        ),
        "requestfailed_count": sum(1 for e in events if e.get("kind") == "requestfailed"),
        "image_events_count": len(image_events),
        "images": images,
        "events": events,
    }
    (out_dir / "render_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--timeout-ms", type=int, default=90000)
    args = parser.parse_args()

    if args.out_dir.exists() and any(args.out_dir.iterdir()):
        raise SystemExit(f"refusing to write into non-empty directory: {args.out_dir}")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    manifest = args.out_dir / "manifest.jsonl"
    records = read_records(args.input_jsonl, args.offset, args.limit)
    for index, record in enumerate(records, start=1):
        case_dir = args.out_dir / f"{index:03d}_{record['instance_id']}"
        project_dir = case_dir / "src"
        shot_dir = case_dir / "render"
        payload: dict[str, Any] = {
            "index": index,
            "instance_id": record["instance_id"],
            "status": "pending",
        }
        try:
            write_files(project_dir, record["input_files"])
            summary = render_case(project_dir, shot_dir, args.timeout_ms)
            payload.update(
                {
                    "status": "ok",
                    "image_count": summary["image_count"],
                    "loaded_image_count": summary["loaded_image_count"],
                    "loadable_image_count": summary["loadable_image_count"],
                    "loaded_loadable_image_count": summary["loaded_loadable_image_count"],
                    "visible_loadable_image_count": summary["visible_loadable_image_count"],
                    "loaded_visible_loadable_image_count": summary["loaded_visible_loadable_image_count"],
                    "requestfailed_count": summary["requestfailed_count"],
                    "report": str(shot_dir / "render_report.json"),
                    "screenshot": str(shot_dir / "screenshot.jpg"),
                }
            )
        except Exception as exc:  # noqa: BLE001
            payload.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
        with manifest.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
