#!/usr/bin/env python3
"""Render health check for locally generated web projects.

Serves each project over local HTTP (same serving mode as the evaluation
harness), loads index.html in headless Chromium, and reports HTTP status,
uncaught page errors, non-resource console errors, HTTP >= 400 responses
(excluding favicon), and whether the page has meaningful content.

Status rules:
  fail: HTTP error / navigation error / blank page / missing local asset
  warn: uncaught pageerror, other console error, failed remote request, or
        canvas-only page with no text
  ok:   renders cleanly with no issues
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import socket
import socketserver
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from playwright.sync_api import sync_playwright

MIN_BODY_TEXT = 80
RESOURCE_NOISE = ("Failed to load resource",)


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def check_project(project_dir: Path, executable: str | None, timeout_ms: int) -> dict:
    result = {"instance_id": project_dir.name, "status": "ok", "reasons": []}
    port = _free_port()
    server = _Server(("127.0.0.1", port),
                     functools.partial(_QuietHandler, directory=str(project_dir)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=executable)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page_errors: list[str] = []
                console_errors: list[str] = []
                http_failures: list[tuple[str, int]] = []
                failed: list[tuple[str, str]] = []
                page.on("pageerror", lambda e: page_errors.append(str(e)))
                page.on("console", lambda m: (
                    console_errors.append(m.text)
                    if m.type == "error" and not m.text.startswith(RESOURCE_NOISE)
                    else None))
                page.on("response", lambda r: (
                    http_failures.append((r.url, r.status))
                    if r.status >= 400 and not r.url.endswith(("favicon.ico", "favicon.png"))
                    else None))
                page.on("requestfailed", lambda r: failed.append(
                    (r.url, (r.failure or {}).get("errorText", "") or "")))
                try:
                    response = page.goto(f"http://127.0.0.1:{port}/index.html",
                                         wait_until="networkidle", timeout=timeout_ms)
                    status = response.status if response else None
                    result["http_status"] = status
                    if response is None or status >= 400:
                        result["status"] = "fail"
                        result["reasons"].append(f"http_status:{status}")
                except Exception as exc:
                    result["status"] = "fail"
                    result["reasons"].append(f"goto:{type(exc).__name__}:{str(exc)[:120]}")
                page.wait_for_timeout(1500)
                body_text = page.evaluate("document.body ? document.body.innerText : ''") or ""
                result["body_text_len"] = len(body_text.strip())
                has_canvas = page.evaluate("document.querySelectorAll('canvas').length") > 0
                has_imgs = page.evaluate("document.images.length") > 0
                result["has_canvas"] = bool(has_canvas)
                result["has_imgs"] = bool(has_imgs)
                if result["body_text_len"] < MIN_BODY_TEXT:
                    if has_canvas or has_imgs:
                        result["status"] = "warn"
                        result["reasons"].append(f"low_text:body_text_len={result['body_text_len']}")
                    else:
                        result["status"] = "fail"
                        result["reasons"].append(f"blank_page:body_text_len={result['body_text_len']}")
                if page_errors:
                    result["status"] = "warn"
                    result["reasons"].append(f"pageerror:{page_errors[0][:120]}")
                    result["page_errors"] = page_errors[:5]
                if console_errors:
                    result["status"] = "warn"
                    result["reasons"].append(f"console_error:{console_errors[0][:120]}")
                    result["console_errors"] = console_errors[:5]
                local_fail = [f for f in http_failures if "127.0.0.1" in f[0]]
                remote_fail = [f for f in http_failures if "127.0.0.1" not in f[0]]
                if local_fail:
                    result["status"] = "fail"
                    result["reasons"].append(f"local_http_fail:{len(local_fail)}:"
                                             f"{local_fail[0][0].split('/')[-1]}")
                    result["local_http_failures"] = [{"url": u[:160], "status": s}
                                                     for u, s in local_fail[:5]]
                if remote_fail:
                    result["status"] = "warn"
                    result["reasons"].append(f"remote_http_fail:{len(remote_fail)}")
                    result["remote_http_failures"] = [{"url": u[:160], "status": s}
                                                      for u, s in remote_fail[:5]]
                if failed:
                    result["status"] = "warn"
                    result["reasons"].append(f"network_failed:{len(failed)}")
                    result["network_failures"] = [{"url": u[:160], "error": e} for u, e in failed[:5]]
            finally:
                browser.close()
    except Exception as exc:
        result["status"] = "error"
        result["reasons"].append(f"{type(exc).__name__}:{str(exc)[:120]}")
    finally:
        server.shutdown()
        server.server_close()
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input-dir", type=Path, required=True, help="Root containing project dirs")
    ap.add_argument("--output-jsonl", type=Path, required=True)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--timeout-ms", type=int, default=30000)
    args = ap.parse_args()

    projects = sorted(p for p in args.input_dir.iterdir() if p.is_dir() and p.name.startswith("abq-"))
    print(f"checking {len(projects)} projects with {args.workers} workers", flush=True)
    executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None

    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    stats = {"ok": 0, "warn": 0, "fail": 0, "error": 0, "done": 0}

    def emit(result: dict) -> None:
        with lock:
            stats[result["status"]] += 1
            stats["done"] += 1
            with open(args.output_jsonl, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(f"  [{stats['done']}/{len(projects)}] {result['instance_id']}: "
                  f"{result['status']} — {'; '.join(result['reasons'])[:100]}", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(check_project, p, executable, args.timeout_ms): p for p in projects}
        for future in as_completed(futures):
            try:
                emit(future.result())
            except Exception as exc:
                emit({"instance_id": futures[future].name, "status": "error",
                      "reasons": [f"{type(exc).__name__}:{exc}"]})
    print(f"DONE ok={stats['ok']} warn={stats['warn']} fail={stats['fail']} error={stats['error']}")


if __name__ == "__main__":
    main()
