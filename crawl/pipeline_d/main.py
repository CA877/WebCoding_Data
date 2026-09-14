#!/usr/bin/env python3
"""Capture final DOM, keep live resource links, and verify networked local replay."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import hashlib
import html as html_module
from io import BytesIO
import json
import multiprocessing as mp
from pathlib import Path
import re
import shutil
import time
from typing import Any
from urllib.parse import urljoin, urlsplit

from PIL import Image, ImageChops, ImageFilter
from playwright.sync_api import sync_playwright

from crawl.pipeline_c.qwen_token_gate import count_project_tokens


TRANSIENT_NAVIGATION_RE = re.compile(
    r"ERR_(?:NETWORK_CHANGED|EMPTY_RESPONSE|SOCKET_NOT_CONNECTED|CONNECTION_RESET|CONNECTION_CLOSED)|"
    r"Timeout \d+ms exceeded",
    re.I,
)

BROKEN_VIEWPORT_IMAGES_JS = """() => [...document.images].filter(img => {
  const box = img.getBoundingClientRect();
  const css = getComputedStyle(img);
  const inViewport = box.width > 1 && box.height > 1 &&
    box.bottom > 0 && box.right > 0 &&
    box.top < window.innerHeight && box.left < window.innerWidth;
  const visible = inViewport && css.display !== 'none' &&
    css.visibility !== 'hidden' && css.opacity !== '0';
  return visible && (!img.complete || img.naturalWidth === 0);
}).length"""

BROKEN_VIEWPORT_IMAGE_DETAILS_JS = """() => {
  const viewportArea = Math.max(innerWidth * innerHeight, 1);
  const broken = [...document.images].flatMap(img => {
    const box = img.getBoundingClientRect();
    const css = getComputedStyle(img);
    const left = Math.max(box.left, 0), top = Math.max(box.top, 0);
    const right = Math.min(box.right, innerWidth), bottom = Math.min(box.bottom, innerHeight);
    const visible = right > left && bottom > top && css.display !== 'none' &&
      css.visibility !== 'hidden' && css.opacity !== '0';
    if (!visible || (img.complete && img.naturalWidth > 0)) return [];
    return [{src: img.currentSrc || img.src || '', area_ratio:
      ((right - left) * (bottom - top)) / viewportArea}];
  });
  return {
    count: broken.length,
    total_area_ratio: broken.reduce((sum, item) => sum + item.area_ratio, 0),
    max_area_ratio: broken.reduce((value, item) => Math.max(value, item.area_ratio), 0),
    urls: broken.slice(0, 20).map(item => item.src),
  };
}"""


def goto_with_transient_retries(page: Any, url: str, timeout_ms: int = 30_000,
                                attempts: int = 3) -> tuple[Any, int]:
    """Retry only explicit transport failures; never loop on HTTP or content rejection."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms), attempt
        except Exception as exc:
            last_error = exc
            if attempt == attempts or not TRANSIENT_NAVIGATION_RE.search(str(exc)):
                raise
            page.wait_for_timeout(750 * attempt)
    raise last_error or RuntimeError("navigation failed without an exception")


def disable_motion(page: Any) -> bool:
    try:
        # ``animation:none`` can freeze modern reveal animations at their
        # invisible initial keyframe.  Run them almost instantly instead so
        # screenshots settle on the authored end state.
        page.add_style_tag(content=(
            "*,*::before,*::after{animation-delay:0s!important;"
            "animation-duration:0.001s!important;animation-iteration-count:1!important;"
            "transition-delay:0s!important;transition-duration:0s!important;"
            "caret-color:transparent!important}"
        ))
        page.wait_for_timeout(100)
        return True
    except Exception:
        return False


def count_broken_viewport_images(page: Any) -> int:
    """Count broken images that can affect the captured viewport."""
    return int(page.evaluate(BROKEN_VIEWPORT_IMAGES_JS))


def broken_viewport_image_details(page: Any) -> dict[str, Any]:
    """Describe broken images by visible footprint, not only element count."""
    details = page.evaluate(BROKEN_VIEWPORT_IMAGE_DETAILS_JS)
    return {
        "count": int(details["count"]),
        "total_area_ratio": round(float(details["total_area_ratio"]), 6),
        "max_area_ratio": round(float(details["max_area_ratio"]), 6),
        "urls": list(details["urls"]),
    }


def project_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]


def token_limit_exceeded(code_tokens: int, max_code_tokens: int) -> bool:
    """Treat a zero limit as unlimited while retaining exact token accounting."""
    return max_code_tokens > 0 and code_tokens > max_code_tokens


def remove_partial_project(output: Path, url: str) -> None:
    shutil.rmtree(output / "projects" / f".{project_id(url)}.partial", ignore_errors=True)


def ensure_external_base(document: str, final_url: str) -> str:
    """Make relative resource references resolve to the live origin on replay."""
    absolute_base = html_module.escape(final_url, quote=True)
    base_pattern = re.compile(r"(<base\b[^>]*?\bhref\s*=\s*)(['\"])(.*?)(\2)", re.I | re.S)
    match = base_pattern.search(document)
    if match:
        resolved = html_module.escape(urljoin(final_url, html_module.unescape(match.group(3))), quote=True)
        return document[:match.start(3)] + resolved + document[match.end(3):]
    head = re.search(r"<head\b[^>]*>", document, re.I)
    base = f'<base href="{absolute_base}">'
    if head:
        return document[:head.end()] + base + document[head.end():]
    return f"<head>{base}</head>" + document


def screenshot_similarity(left: bytes, right: bytes) -> float:
    """Return a simple viewport-level RGB similarity in [0, 1]."""
    first = Image.open(BytesIO(left)).convert("RGB")
    second = Image.open(BytesIO(right)).convert("RGB")
    if second.size != first.size:
        second = second.resize(first.size)
    histogram = ImageChops.difference(first, second).histogram()
    difference = sum((index % 256) * count for index, count in enumerate(histogram))
    maximum = first.width * first.height * 3 * 255
    return round(1.0 - difference / max(maximum, 1), 6)


def screenshot_edge_density(data: bytes) -> float:
    """Measure whether a viewport contains more than a near-uniform app shell."""
    image = Image.open(BytesIO(data)).convert("L")
    edges = image.filter(ImageFilter.FIND_EDGES)
    if image.width > 4 and image.height > 4:
        edges = edges.crop((2, 2, image.width - 2, image.height - 2))
    histogram = edges.histogram()
    return round(sum(histogram[20:]) / max(sum(histogram), 1), 6)


def viewport_visible_text_chars(page: Any) -> int:
    return int(page.evaluate("""() => {
      const visible = el => {
        const box = el.getBoundingClientRect(), css = getComputedStyle(el);
        return box.width > 1 && box.height > 1 && box.bottom > 0 && box.right > 0 &&
          box.top < innerHeight && box.left < innerWidth && css.display !== 'none' &&
          css.visibility !== 'hidden' && css.opacity !== '0';
      };
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let count = 0;
      for (let node = walker.nextNode(); node; node = walker.nextNode()) {
        const value = node.nodeValue.trim();
        if (value && node.parentElement && visible(node.parentElement)) count += value.length;
      }
      return count;
    }"""))


def viewport_interactive_element_count(page: Any) -> int:
    """Count visible first-viewport interaction affordances without activating them."""
    return int(page.evaluate("""() => [...document.querySelectorAll(
      'a[href],button,input,select,textarea,summary,[role="button"],[role="link"],[tabindex]')]
      .filter(el => {
        const box = el.getBoundingClientRect(), css = getComputedStyle(el);
        return box.width > 1 && box.height > 1 && box.bottom > 0 && box.right > 0 &&
          box.top < innerHeight && box.left < innerWidth && css.display !== 'none' &&
          css.visibility !== 'hidden' && css.opacity !== '0' && !el.disabled;
      }).length"""))


def newly_introduced_errors(source_errors: list[str], replay_errors: list[str]) -> list[str]:
    """Keep replay errors that were not already emitted by the live source page."""
    return list((Counter(replay_errors) - Counter(source_errors)).elements())


def _resource_type(failure: str) -> str:
    parts = failure.split(":", 2)
    return parts[1] if len(parts) == 3 else "unknown"


def _resource_url(failure: str) -> str:
    parts = failure.split(":", 2)
    return parts[2] if len(parts) == 3 else ""


def _same_origin(url: str, final_url: str) -> bool:
    return bool(urlsplit(url).hostname and urlsplit(url).hostname == urlsplit(final_url).hostname)


def evaluate_replay_admission(metrics: dict[str, Any], profile: str = "strict", *,
                              min_text_chars: int = 300) -> dict[str, Any]:
    """Return all hard failures and warnings for strict or inspiration admission."""
    failures: list[str] = []
    warnings: list[str] = []

    if (metrics.get("http_status") or 0) >= 400:
        failures.append(f"replay_http_{metrics.get('http_status')}")
    if metrics.get("page_errors") and metrics.get("screenshot_similarity", 0) < 0.85:
        failures.append("replay_page_error_with_visual_mismatch")
    source_incomplete = (
        metrics.get("source_viewport_visible_text_chars", 0) < 100 and
        metrics.get("source_screenshot_edge_density", 0) < 0.01
    )
    replay_incomplete = (
        metrics.get("viewport_visible_text_chars", 0) < 100 and
        metrics.get("screenshot_edge_density", 0) < 0.01
    )
    if source_incomplete:
        if profile == "strict" or replay_incomplete:
            failures.append("source_incomplete_viewport")
        else:
            warnings.append("source_initial_state_incomplete")
    if replay_incomplete:
        failures.append("replay_incomplete_viewport")
    if metrics.get("text_chars", 0) < min_text_chars or metrics.get("text_retention_ratio", 0) < 0.6:
        failures.append("replay_content_missing")
    if metrics.get("text_retention_ratio", 0) > 1.15:
        if profile == "inspiration" and source_incomplete and not replay_incomplete:
            warnings.append("replay_has_more_content_than_source_initial_state")
        else:
            failures.append("replay_content_duplicated")
    if metrics.get("screenshot_similarity", 0) < 0.85:
        if profile == "inspiration" and source_incomplete and not replay_incomplete:
            warnings.append("source_replay_dynamic_state_mismatch")
        else:
            failures.append("replay_visual_mismatch")
    source_interactive = int(metrics.get("source_viewport_interactive_elements", 0))
    replay_interactive = int(metrics.get("viewport_interactive_elements", 0))
    if source_interactive and replay_interactive / source_interactive < 0.6:
        failures.append("replay_interaction_affordances_missing")

    resource_failures = sorted(set(
        metrics.get("source_critical_resource_failures", []) +
        metrics.get("critical_resource_failures", [])
    ))
    if profile == "strict":
        if resource_failures:
            failures.append("replay_critical_resource_failure")
        if metrics.get("broken_visible_images", 0):
            failures.append("replay_broken_visible_images")
    elif profile == "inspiration":
        final_url = str(metrics.get("final_url", ""))
        hard_resources = [failure for failure in resource_failures if
                          _resource_type(failure) in {"document", "stylesheet"} or
                          (_resource_type(failure) == "script" and
                           _same_origin(_resource_url(failure), final_url))]
        soft_resources = [failure for failure in resource_failures if failure not in hard_resources]
        if hard_resources:
            failures.append("core_resource_failure")
        if soft_resources:
            warnings.append("nonessential_resource_failure")

        source_broken = metrics.get("source_broken_image_details") or {}
        replay_broken = metrics.get("replay_broken_image_details") or {}
        broken_count = max(int(source_broken.get("count", 0)),
                           int(replay_broken.get("count", metrics.get("broken_visible_images", 0))))
        if broken_count:
            minor = bool(
                source_broken and replay_broken and broken_count <= 2 and
                max(source_broken.get("max_area_ratio", 1),
                    replay_broken.get("max_area_ratio", 1)) <= 0.02 and
                max(source_broken.get("total_area_ratio", 1),
                    replay_broken.get("total_area_ratio", 1)) <= 0.03
            )
            if minor:
                warnings.append("minor_broken_visible_images")
            else:
                failures.append("material_broken_visible_images")
    else:
        raise ValueError(f"unknown admission profile: {profile}")

    return {
        "accepted": not failures,
        "primary_reason": failures[0] if failures else None,
        "failure_reasons": list(dict.fromkeys(failures)),
        "warnings": list(dict.fromkeys(warnings)),
    }


def replay_rejection_reason(metrics: dict[str, Any], profile: str = "strict") -> str | None:
    return evaluate_replay_admission(metrics, profile)["primary_reason"]


def completed_source_urls(manifest: Path) -> set[str]:
    completed: set[str] = set()
    if not manifest.is_file():
        return completed
    for line in manifest.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("quality_status") == "retryable":
            continue
        if row.get("source_url"):
            completed.add(str(row["source_url"]))
    return completed


def completed_pass_count(manifest: Path) -> int:
    """Count latest successful rows so a resumed target is cumulative."""
    latest: dict[str, str] = {}
    if not manifest.is_file():
        return 0
    for line in manifest.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("source_url"):
            latest[str(row["source_url"])] = str(row.get("status", ""))
    return sum(status == "pass" for status in latest.values())


def crawl_one(url: str, output: Path, browser_proxy: str, wait_ms: int,
              tokenizer: Path, max_code_tokens: int, admission_profile: str = "inspiration",
              preserve_html: bool = False) -> dict[str, Any]:
    started = time.monotonic()
    pid = project_id(url)
    target = output / "projects" / pid
    temporary = output / "projects" / f".{pid}.partial"
    shutil.rmtree(temporary, ignore_errors=True)
    temporary.mkdir(parents=True, exist_ok=True)
    evidence_dir = output / "render_evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    source_evidence = evidence_dir / f"{pid}_source.png"
    replay_evidence = evidence_dir / f"{pid}_replay.png"
    replay_metrics: dict[str, Any] | None = None
    try:
        with sync_playwright() as playwright:
            proxy = None
            if browser_proxy:
                proxy = {"server": browser_proxy, "bypass": "localhost,127.0.0.1"}
            browser = playwright.chromium.launch(
                headless=True,
                proxy=proxy,
            )
            context = browser.new_context(viewport={"width": 1280, "height": 800}, ignore_https_errors=True)
            page = context.new_page()
            source_page_errors: list[str] = []
            source_critical_failures: list[str] = []
            page.on("pageerror", lambda exc: source_page_errors.append(str(exc)[:500]))

            def note_source_response(item: Any) -> None:
                if item.status >= 400 and item.request.resource_type in {"document", "script", "stylesheet", "font"}:
                    source_critical_failures.append(
                        f"{item.status}:{item.request.resource_type}:{item.url}")

            def note_source_failed(request: Any) -> None:
                if request.resource_type in {"document", "script", "stylesheet", "font"}:
                    source_critical_failures.append(f"failed:{request.resource_type}:{request.url}")

            page.on("response", note_source_response)
            page.on("requestfailed", note_source_failed)
            response, source_navigation_attempts = goto_with_transient_retries(page, url)
            if response is None or response.status >= 400:
                raise RuntimeError(f"navigation_failed:{response.status if response else 'no_response'}")
            page.wait_for_timeout(wait_ms)
            source_html = page.content()
            final_url = page.url
            status_code = response.status
            source_text_chars = len(page.locator("body").inner_text(timeout=10_000).strip())
            external_reference_count = page.evaluate(
                """() => [...document.querySelectorAll('script[src],link[href],img[src],source[src],video[src],audio[src]')]
                  .filter(el => { const value = el.src || el.href; return value && /^https?:/.test(value); }).length"""
            )
            source_motion_disabled = disable_motion(page)
            source_screenshot = page.screenshot(full_page=False)
            source_viewport_visible_text_chars = viewport_visible_text_chars(page)
            source_viewport_interactive_elements = viewport_interactive_element_count(page)
            source_broken_image_details = broken_viewport_image_details(page)

            saved_html = source_html if preserve_html else ensure_external_base(source_html, final_url)
            (temporary / "index.html").write_text(saved_html, encoding="utf-8")
            critical_failures: list[str] = []
            replay_page_errors: list[str] = []
            external_requests: set[str] = set()
            replay_context = (browser.new_context(viewport={"width": 1280, "height": 800},
                              service_workers="block") if preserve_html else context)
            replay = replay_context.new_page()

            def note_response(item: Any) -> None:
                request = item.request
                if urlsplit(item.url).scheme in {"http", "https"} and urlsplit(item.url).hostname not in {"127.0.0.1", "localhost"}:
                    external_requests.add(item.url)
                if item.status >= 400 and request.resource_type in {"document", "script", "stylesheet", "font"}:
                    critical_failures.append(f"{item.status}:{request.resource_type}:{item.url}")

            def note_failed(request: Any) -> None:
                if request.resource_type in {"document", "script", "stylesheet", "font"}:
                    critical_failures.append(f"failed:{request.resource_type}:{request.url}")

            replay.on("response", note_response)
            replay.on("requestfailed", note_failed)
            replay.on("pageerror", lambda exc: replay_page_errors.append(str(exc)[:500]))

            def serve_saved_document(route: Any) -> None:
                if route.request.resource_type == "document":
                    route.fulfill(status=200, content_type="text/html; charset=utf-8", body=saved_html)
                else:
                    route.continue_()

            replay.route(final_url, serve_saved_document)
            replay_response, replay_navigation_attempts = goto_with_transient_retries(replay, final_url)
            replay.wait_for_timeout(wait_ms)
            replay_text_chars = len(replay.locator("body").inner_text(timeout=10_000).strip())
            replay_broken_image_details = broken_viewport_image_details(replay)
            broken_visible_images = replay_broken_image_details["count"]
            replay_motion_disabled = disable_motion(replay)
            replay_screenshot = replay.screenshot(full_page=False)
            replay_viewport_visible_text_chars = viewport_visible_text_chars(replay)
            replay_viewport_interactive_elements = viewport_interactive_element_count(replay)
            replay_metrics = {
                "mode": "origin_preserving_document_intercept",
                "final_url": final_url,
                "admission_profile": admission_profile,
                "source_navigation_attempts": source_navigation_attempts,
                "replay_navigation_attempts": replay_navigation_attempts,
                "source_motion_disabled": source_motion_disabled,
                "replay_motion_disabled": replay_motion_disabled,
                "source_viewport_visible_text_chars": source_viewport_visible_text_chars,
                "source_viewport_interactive_elements": source_viewport_interactive_elements,
                "source_screenshot_edge_density": screenshot_edge_density(source_screenshot),
                "http_status": replay_response.status if replay_response else None,
                "text_chars": replay_text_chars,
                "text_retention_ratio": round(replay_text_chars / max(source_text_chars, 1), 4),
                "broken_visible_images": broken_visible_images,
                "source_broken_image_details": source_broken_image_details,
                "replay_broken_image_details": replay_broken_image_details,
                "viewport_visible_text_chars": replay_viewport_visible_text_chars,
                "viewport_interactive_elements": replay_viewport_interactive_elements,
                "screenshot_edge_density": screenshot_edge_density(replay_screenshot),
                "critical_resource_failures": sorted(set(critical_failures))[:40],
                "source_critical_resource_failures": sorted(set(source_critical_failures))[:40],
                "source_page_errors": source_page_errors[:20],
                "page_errors": newly_introduced_errors(source_page_errors, replay_page_errors)[:20],
                "external_request_count": len(external_requests),
                "screenshot_similarity": screenshot_similarity(source_screenshot, replay_screenshot),
            }
            replay.close()
            if preserve_html:
                replay_context.close()
            context.close()
            browser.close()
        source_evidence.write_bytes(source_screenshot)
        replay_evidence.write_bytes(replay_screenshot)
        admission = evaluate_replay_admission(replay_metrics, admission_profile)
        replay_metrics["admission"] = admission
        if not admission["accepted"]:
            raise RuntimeError(admission["primary_reason"] + ":" + json.dumps(replay_metrics, ensure_ascii=False))
        code_tokens = count_project_tokens(temporary, tokenizer)
        if token_limit_exceeded(code_tokens, max_code_tokens):
            shutil.rmtree(temporary, ignore_errors=True)
            shutil.rmtree(target, ignore_errors=True)
            return {
                "source_url": url,
                "final_url": final_url,
                "project_id": pid,
                "status": "token_rejected",
                "quality_status": "reject",
                "reason": f"qwen_code_tokens_over_limit:{code_tokens}>{max_code_tokens}",
                "code_tokens": code_tokens,
                "max_code_tokens": max_code_tokens,
                "html_bytes": len(saved_html.encode("utf-8")),
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
        metadata = {
            "source_url": url,
            "final_url": final_url,
            "http_status": status_code,
            "capture": "playwright_final_dom",
            "resource_policy": ("original_dom_and_online_resources" if preserve_html else
                                "external_references_with_absolute_base_no_resource_downloads"),
            "resource_files_downloaded": 0,
            "external_reference_count": external_reference_count,
            "render_validation": replay_metrics,
            "admission_profile": admission_profile,
            "admission_warnings": admission["warnings"],
            "render_evidence": {
                "source": str(source_evidence.relative_to(output)),
                "replay": str(replay_evidence.relative_to(output)),
            },
            "code_tokens": code_tokens,
            "max_code_tokens": max_code_tokens or None,
            "token_limit_enabled": max_code_tokens > 0,
        }
        (temporary / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.rmtree(target, ignore_errors=True)
        temporary.rename(target)
        return {
            **metadata,
            "project_id": pid,
            "status": "pass",
            "quality_status": ("inspiration_candidate" if admission_profile == "inspiration"
                               else "render_verified"),
            "html_bytes": len(saved_html.encode("utf-8")),
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    except Exception as exc:
        shutil.rmtree(temporary, ignore_errors=True)
        return {
            "source_url": url,
            "project_id": pid,
            "status": "crawl_failed",
            "quality_status": "retryable",
            "reason": f"{type(exc).__name__}:{exc}",
            "render_validation": replay_metrics,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }


def _entry(url: str, output: str, browser_proxy: str, wait_ms: int,
           tokenizer: str, max_code_tokens: int, admission_profile: str, queue: Any) -> None:
    queue.put(crawl_one(url, Path(output), browser_proxy, wait_ms, Path(tokenizer),
                        max_code_tokens, admission_profile))


def crawl_with_timeout(url: str, output: Path, browser_proxy: str, wait_ms: int, site_timeout: int,
                       tokenizer: Path, max_code_tokens: int,
                       admission_profile: str = "inspiration") -> dict[str, Any]:
    context = mp.get_context("spawn")
    queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_entry,
        args=(url, str(output), browser_proxy, wait_ms, str(tokenizer), max_code_tokens,
              admission_profile, queue),
    )
    process.start()
    process.join(site_timeout)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)
        remove_partial_project(output, url)
        return {
            "source_url": url,
            "project_id": project_id(url),
            "status": "site_timeout",
            "quality_status": "retryable",
            "reason": f"site_timeout:{site_timeout}s",
        }
    try:
        return queue.get(timeout=1)
    except Exception:
        remove_partial_project(output, url)
        return {
            "source_url": url,
            "project_id": project_id(url),
            "status": "worker_exited",
            "quality_status": "retryable",
            "reason": f"worker_exit_code:{process.exitcode}",
        }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pipeline D: HTML-only capture with external resources and render-verified local replay"
    )
    parser.add_argument("--urls", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-proxy", default="")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--wait-ms", type=int, default=3000)
    parser.add_argument("--site-timeout", type=int, default=120)
    parser.add_argument("--qwen-tokenizer", type=Path, required=True)
    parser.add_argument("--max-code-tokens", type=int, default=0,
                        help="Optional exact HTML token limit; 0 disables rejection")
    parser.add_argument("--target-passes", type=int, default=0,
                        help="Stop after this many render-verified projects; 0 processes all URLs")
    parser.add_argument("--admission-profile", choices=("inspiration", "strict"),
                        default="inspiration",
                        help="Inspiration tolerates minor nonessential resource defects; strict does not")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    if args.workers < 1 or args.site_timeout < 1 or args.max_code_tokens < 0 or args.target_passes < 0:
        parser.error("workers and site-timeout must be positive; token/pass limits cannot be negative")
    if not args.qwen_tokenizer.is_file():
        parser.error(f"Qwen tokenizer does not exist: {args.qwen_tokenizer}")

    urls = [line.strip() for line in args.urls.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        urls = urls[: args.limit]
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = args.output / "manifest.jsonl"
    existing_passes = completed_pass_count(manifest)
    if args.resume:
        done = completed_source_urls(manifest)
        urls = [url for url in urls if url not in done]
        print(f"resume: skipped={len(done)} remaining={len(urls)}", flush=True)
    if args.target_passes and existing_passes >= args.target_passes:
        print(f"target already met: pass={existing_passes} target={args.target_passes}", flush=True)
        return
    quality_gates = [
        "origin_preserving_saved_document_http_200", "complete_source_and_replay_viewport",
        "no_new_page_errors_with_visual_mismatch", "0.6<=text_retention<=1.15",
        "viewport_similarity>=0.85", "interactive_affordance_retention>=0.6",
    ]
    if args.admission_profile == "strict":
        quality_gates += ["external_css_js_fonts_load", "no_visible_broken_images"]
    else:
        quality_gates += [
            "no_core_document_stylesheet_or_same_origin_script_failure",
            "only_minor_broken_images_may_warn",
        ]
    if args.max_code_tokens:
        quality_gates.insert(0, f"qwen_exact_html_tokens<={args.max_code_tokens}")
    config = {
        "pipeline": "D",
        "input_urls": str(args.urls),
        "workers": args.workers,
        "wait_ms": args.wait_ms,
        "site_timeout": args.site_timeout,
        "browser_proxy": args.browser_proxy,
        "capture": "playwright_final_dom",
        "resource_policy": "external_references_with_absolute_base_no_resource_downloads",
        "admission_profile": args.admission_profile,
        "quality_gates": quality_gates,
        "qwen_tokenizer": str(args.qwen_tokenizer),
        "max_code_tokens": args.max_code_tokens or None,
        "token_limit_enabled": args.max_code_tokens > 0,
        "target_passes": args.target_passes,
    }
    (args.output / "run_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8")

    with manifest.open("a", encoding="utf-8") as handle, ThreadPoolExecutor(max_workers=args.workers) as pool:
        source = iter(enumerate(urls, 1))
        pending = {}
        passes = existing_passes

        def submit_one() -> bool:
            try:
                index, url = next(source)
            except StopIteration:
                return False
            future = pool.submit(
                crawl_with_timeout, url, args.output, args.browser_proxy, args.wait_ms, args.site_timeout,
                args.qwen_tokenizer, args.max_code_tokens, args.admission_profile)
            pending[future] = (index, url)
            return True

        for _ in range(args.workers):
            if not submit_one():
                break
        completed = 0
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                index, url = pending.pop(future)
                try:
                    row = future.result()
                except Exception as exc:
                    row = {"source_url": url, "status": "worker_error", "quality_status": "retryable", "reason": repr(exc)}
                completed += 1
                passes += int(row.get("status") == "pass")
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                handle.flush()
                print(f"[{completed}/{len(urls)}; input={index}; pass={passes}] {url}: {row['status']}", flush=True)
            target_met = bool(args.target_passes and passes >= args.target_passes)
            if not target_met:
                while len(pending) < args.workers and submit_one():
                    pass
            elif not pending:
                break


if __name__ == "__main__":
    main()
