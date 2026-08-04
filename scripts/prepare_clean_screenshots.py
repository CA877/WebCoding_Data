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


def screenshot_project(project_dir: Path, port: int) -> Path:
    project_dir = project_dir.resolve()
    handler = functools.partial(_QuietHandler, directory=str(project_dir))
    server = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    out = project_dir / f"{project_dir.name}_clean.png"
    try:
        with sync_playwright() as p:
            executable_path = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None
            browser = p.chromium.launch(headless=True, executable_path=executable_path)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"http://127.0.0.1:{port}/index.html", wait_until="networkidle", timeout=60_000)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(out), full_page=True)
            browser.close()
    finally:
        server.shutdown()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--projects", nargs="+", type=Path, required=True)
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()
    for i, project in enumerate(args.projects):
        out = screenshot_project(project, args.port or 9200 + i)
        print(f"{project.name}: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
