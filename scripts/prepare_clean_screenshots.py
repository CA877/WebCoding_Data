#!/usr/bin/env python3
"""Capture a clean full-page desktop screenshot for each project directory.

Writes <project>/<project_name>_clean.png so the edit/repair constructors can
find project-root screenshots (they glob <name>*.png).  Serves each project
over local HTTP like Pipeline C.
"""
from __future__ import annotations

import argparse
import http.server
import functools
import os
import socketserver
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def screenshot_project(
    project_dir: Path,
    port: int,
    browser_proxy: str = "",
    width: int = 1920,
    height: int = 1080,
) -> Path:
    project_dir = project_dir.resolve()
    handler = functools.partial(_QuietHandler, directory=str(project_dir))
    server = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    out = project_dir / f"{project_dir.name}_clean.png"
    try:
        with sync_playwright() as p:
            executable_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None
            launch_options = {"headless": True, "executable_path": executable_path}
            if browser_proxy:
                launch_options["proxy"] = {"server": browser_proxy}
            browser = p.chromium.launch(**launch_options)
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(
                f"http://127.0.0.1:{port}/index.html",
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            page.wait_for_timeout(1500)
            page.screenshot(path=str(out), full_page=True)
            browser.close()
    finally:
        server.shutdown()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    source = ap.add_mutually_exclusive_group(required=True)
    source.add_argument("--projects", nargs="+", type=Path)
    source.add_argument("--project-list", type=Path)
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--browser-proxy", default="")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    args = ap.parse_args()
    projects = args.projects
    if args.project_list:
        with args.project_list.open("r", encoding="utf-8") as handle:
            projects = [Path(line.strip()) for line in handle if line.strip()]
    assert projects is not None
    for i, project in enumerate(projects):
        out = screenshot_project(
            project,
            args.port or 9200 + i,
            args.browser_proxy,
            args.width,
            args.height,
        )
        print(f"{project.name}: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
