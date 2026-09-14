#!/usr/bin/env python3
"""Measure real rendered-page complexity before an expensive strict crawl."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import functools
import json
import multiprocessing as mp
import queue
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from crawl.pipeline_c.main import goto_with_network_retries


CHALLENGE_RE = re.compile(
    r"verify you are human|checking your browser|just a moment|captcha|cf-challenge|access denied",
    re.I,
)


def summarize_entries(entries: list[dict], html_bytes: int, text_chars: int,
                      challenge: bool) -> dict:
    counts = {kind: 0 for kind in ("script", "link", "img", "css", "font")}
    js_css_bytes = 0
    transfer_bytes = html_bytes
    third_party = 0
    for entry in entries:
        kind = str(entry.get("initiatorType") or "other")
        if kind in counts:
            counts[kind] += 1
        transfer = max(0, int(entry.get("transferSize") or entry.get("encodedBodySize") or 0))
        transfer_bytes += transfer
        name = str(entry.get("name") or "")
        if kind in {"script", "link", "css"} or re.search(r"\.(?:js|css)(?:[?#]|$)", name, re.I):
            js_css_bytes += transfer
        if entry.get("thirdParty"):
            third_party += 1
    return {
        "request_count": len(entries) + 1,
        "script_request_count": counts["script"],
        "stylesheet_request_count": counts["link"] + counts["css"],
        "image_request_count": counts["img"],
        "font_request_count": counts["font"],
        "third_party_request_count": third_party,
        "html_bytes": html_bytes,
        "js_css_transfer_bytes": js_css_bytes,
        "code_transfer_proxy_bytes": html_bytes + js_css_bytes,
        "total_transfer_bytes": transfer_bytes,
        "text_chars": text_chars,
        "challenge": challenge,
    }


def summarize_dom(raw: dict) -> dict:
    """Normalize browser DOM metrics and compute a bounded richness score."""
    counts = {str(key): max(0, int(value or 0)) for key, value in raw.get("component_counts", {}).items()}
    component_types = sorted(key for key, value in counts.items() if value)
    interactive = sum(counts.get(key, 0) for key in ("buttons", "forms", "inputs", "disclosure", "dialogs", "tabs"))
    style_signals = max(0, int(raw.get("style_signal_count") or 0))
    patterns = sorted(set(map(str, raw.get("named_ui_patterns", []))))
    edit_evidence = {
        str(name): max(0, int(value or 0))
        for name, value in raw.get("webcompass_edit_evidence", {}).items()
    }
    edit_capabilities = sorted(name for name, value in edit_evidence.items() if value)
    atomic_features = sorted(set(map(str, raw.get("atomic_ui_features", []))))
    score = (
        min(len(component_types), 10) * 1.3
        + min(interactive, 15) * 0.35
        + min(len(patterns), 8) * 0.7
        + min(counts.get("images", 0), 12) * 0.15
        + min(style_signals, 80) * 0.025
        + min(max(0, int(raw.get("viewport_count") or 0)), 8) * 0.2
    )
    if counts.get("sections", 0) >= 3:
        score += 0.8
    return {
        "component_counts": counts,
        "component_types": component_types,
        "interactive_control_count": interactive,
        "named_ui_patterns": patterns,
        "style_signal_count": style_signals,
        "viewport_count": max(0, int(raw.get("viewport_count") or 0)),
        "richness_score": round(score, 3),
        "page_title": str(raw.get("page_title") or "")[:300],
        "webcompass_edit_capabilities": edit_capabilities,
        "webcompass_edit_evidence": edit_evidence,
        "atomic_ui_features": atomic_features,
    }


def probe_page(page, url: str, timeout_ms: int, wait_ms: int, navigation_attempts: int = 1) -> dict:
    retries = 0

    def note_retry(_exc: Exception) -> None:
        nonlocal retries
        retries += 1

    response = goto_with_network_retries(
        page, url, wait_until="domcontentloaded", timeout=timeout_ms,
        attempts=navigation_attempts, on_retry=note_retry,
    )
    page.wait_for_timeout(wait_ms)
    html = page.content()
    text = page.locator("body").inner_text(timeout=min(timeout_ms, 10_000))
    root_host = page.evaluate("location.hostname")
    entries = page.evaluate(
        """rootHost => performance.getEntriesByType('resource').map(entry => ({
          name: entry.name,
          initiatorType: entry.initiatorType,
          transferSize: entry.transferSize,
          encodedBodySize: entry.encodedBodySize,
          thirdParty: (() => { try { return new URL(entry.name).hostname !== rootHost; } catch (_) { return false; } })()
        }))""",
        root_host,
    )
    raw_dom = page.evaluate(
        r"""() => {
          const count = selector => document.querySelectorAll(selector).length;
          const html = document.documentElement.innerHTML.toLowerCase();
          const scripts = [...document.scripts].map(el => `${el.src} ${el.textContent || ''}`).join(' ').toLowerCase();
          const has = pattern => pattern.test(html + ' ' + scripts);
          const names = new Set();
          const pattern = /(?:^|[-_ ])(hero|card|carousel|slider|gallery|modal|dialog|tabs?|accordion|dropdown|menu|navbar|sidebar|breadcrumb|pagination|toast|tooltip|timeline|pricing|testimonial|feature|portfolio|product)(?:$|[-_ ])/i;
          for (const el of document.querySelectorAll('[class]')) {
            for (const value of el.classList) {
              const match = value.match(pattern); if (match) names.add(match[1].toLowerCase());
            }
          }
          let styleSignals = 0;
          for (const el of [...document.querySelectorAll('body *')].slice(0, 2500)) {
            const box = el.getBoundingClientRect();
            if (box.width < 2 || box.height < 2) continue;
            const css = getComputedStyle(el);
            if (css.display === 'grid' || css.display === 'flex' || css.boxShadow !== 'none' || parseFloat(css.borderRadius) >= 6 || css.animationName !== 'none') styleSignals++;
          }
          const interactiveTables = [...document.querySelectorAll('table, [role=grid], [role=treegrid]')].filter(table => {
            const container = table.closest('[class*=table], [class*=grid]') || table.parentElement || table;
            const hasDataRows = table.querySelectorAll('tbody tr').length >= 3 && table.querySelectorAll('th').length >= 1;
            return table.matches('.dataTable, .datatable, .ag-root, [role=grid], [role=treegrid]') ||
              !!table.querySelector('[aria-sort], th button') ||
              (hasDataRows && !!table.querySelector('tbody input, tbody select, td[contenteditable=true]')) ||
              !!container.querySelector('[class*=pagination], [aria-label*=pagination i]') ||
              (hasDataRows && /sort by|filter|rows per page|page \d+ of \d+/i.test(container.innerText || ''));
          });
          const authForms = [...document.forms].filter(form => {
            const text = form.innerText || '';
            return !!form.querySelector('input[type=password]') ||
              (!!form.querySelector('input[type=email], input[name*=user i], input[autocomplete=username]') &&
                /sign in|log in|register|forgot password/i.test(text));
          });
          const cartControls = [...document.querySelectorAll(
            '[class*=shopping-cart], [class*=cart-item], [class*=cart-drawer], [data-cart], [aria-label*=cart i], button, a'
          )].filter(el => /add to cart|view cart|shopping cart|checkout/i.test(el.innerText || el.getAttribute('aria-label') || ''));
          const dashboardRoots = count('[class*=dashboard], [data-dashboard], [class*=metric-card], [class*=sparkline]');
          const dashboardCharts = count('[class*=dashboard] canvas, [class*=dashboard] svg, [class*=dashboard] [class*=chart], [class*=metric-card], [class*=sparkline]');
          const infiniteControls = count('[class*=infinite-scroll], [data-infinite-scroll], [class*=load-more], button[aria-label*=load-more i]');
          const wizardParts = count('[class*=wizard], [data-step], [aria-current=step]');
          const notificationParts = count('[class*=notification-center], [class*=notification-bell], [class*=notification-dropdown], [data-notification], [aria-label*=notification i]');
          const evidence = {
            data_table: interactiveTables.length,
            rich_text_editor: count('[contenteditable=true], .ql-editor, .prosemirror, .tox-edit-area, .ck-editor, [role=textbox][aria-multiline=true]'),
            drag_drop_interface: count('[draggable=true], .dropzone, [data-dropzone], [class*=drag-and-drop], [class*=sortable]'),
            tree_view: count('[role=tree], [role=treeitem], .tree-view, .treeview, .jstree'),
            real_time_dashboard: dashboardRoots && (dashboardCharts || has(/websocket|eventsource/)) ? dashboardRoots : 0,
            infinite_scroll: infiniteControls || (has(/infinite[-_ ]?scroll/) && has(/intersectionobserver|load[-_ ]?more/)) ? 1 : 0,
            async_form_validation: (count('form') && has(/aria-invalid|validation-message|debounc|async-validation|validating/)) ? 1 : 0,
            file_upload_progress: count('input[type=file]') && (count('progress, [role=progressbar]') || has(/upload-progress|uploading/)) ? 1 : 0,
            parallax_scrolling: has(/parallax|data-scroll-speed|background-attachment\s*:\s*fixed/) ? 1 : 0,
            page_transitions: has(/view-transition|page-transition|route-transition|transition-enter|transition-leave/) ? 1 : 0,
            particle_effects: count('canvas') && has(/particles?\.js|tsparticles|particle-system|particle/) ? 1 : 0,
            skeleton_loading: count('[class*=skeleton], [class*=shimmer], [aria-busy=true]'),
            shopping_cart: cartControls.length,
            user_authentication: authForms.length,
            multi_step_wizard: wizardParts >= 2 || (wizardParts && has(/multi[-_ ]?step|wizard/)) ? wizardParts : 0,
            notification_center: notificationParts || (has(/unread[-_ ]?(badge|count)|mark[-_ ]?as[-_ ]?read/) && count('[role=status], [class*=badge]')) ? 1 : 0
          };
          const atomic = [];
          const atomicSelectors = {
            tabs: '[role=tab], [role=tablist]', accordion: 'details, [aria-expanded]',
            dropdown: 'select, [aria-haspopup=listbox], [class*=dropdown]', dialog: 'dialog, [role=dialog]',
            breadcrumb: '[aria-label*=breadcrumb i], .breadcrumb', pagination: '[aria-label*=pagination i], .pagination',
            search: 'input[type=search], [role=search]', checkbox: 'input[type=checkbox], [role=checkbox]',
            radio: 'input[type=radio], [role=radio]', toggle: '[role=switch], input[type=checkbox][class*=toggle]',
            range: 'input[type=range]', date_picker: 'input[type=date], [class*=datepicker]',
            file_input: 'input[type=file]', progress: 'progress, [role=progressbar]',
            carousel: '[class*=carousel], [class*=slider]', gallery: '[class*=gallery]',
            cards: '[class*=card]', chart: 'canvas, [class*=chart]', video: 'video',
            tooltip: '[role=tooltip], [class*=tooltip]', toast: '[role=status], [class*=toast]',
            selected_state: '[aria-selected=true]', expanded_state: '[aria-expanded]', disabled_state: ':disabled, [aria-disabled=true]',
            loading_state: '[aria-busy=true], [class*=loading], [class*=skeleton]'
          };
          for (const [name, selector] of Object.entries(atomicSelectors)) if (count(selector)) atomic.push(name);
          return {
            page_title: document.title,
            viewport_count: Math.ceil(document.documentElement.scrollHeight / Math.max(innerHeight, 1)),
            style_signal_count: styleSignals,
            named_ui_patterns: [...names],
            webcompass_edit_evidence: evidence,
            atomic_ui_features: atomic,
            component_counts: {
              navigation: count('nav, [role=navigation]'),
              sections: count('main, section, article'),
              buttons: count('button, [role=button]'),
              forms: count('form'),
              inputs: count('input, select, textarea, [role=checkbox], [role=radio], [role=switch]'),
              disclosure: count('details, summary, [aria-expanded]'),
              dialogs: count('dialog, [role=dialog]'),
              tabs: count('[role=tab], [role=tablist]'),
              tables: count('table, [role=grid]'),
              images: count('img, picture'),
              media: count('video, audio, canvas, svg')
            }
          };
        }"""
    )
    metrics = summarize_entries(
        entries, len(html.encode("utf-8")), len(text), bool(CHALLENGE_RE.search(html[:100_000]))
    )
    return {
        "status": "ok",
        "url": url,
        "final_url": page.url,
        "http_status": response.status if response else None,
        "navigation_retries": retries,
        **metrics, **summarize_dom(raw_dom),
    }


def append_jsonl(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()


def probe_url_worker(result_queue, url: str, timeout_seconds: int, wait_ms: int,
                     browser_proxy: str | None) -> None:
    started = time.monotonic()
    try:
        with sync_playwright() as playwright:
            launch = {"headless": True}
            if browser_proxy:
                launch["proxy"] = {"server": browser_proxy}
            browser = playwright.chromium.launch(**launch)
            context = browser.new_context(ignore_https_errors=True, viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            try:
                row = probe_page(page, url, timeout_seconds * 1000, wait_ms)
            finally:
                page.close()
                context.close()
                browser.close()
    except Exception as exc:
        row = {"status": "error", "url": url, "error_type": type(exc).__name__, "error": str(exc)[:1000]}
    row["elapsed_seconds"] = round(time.monotonic() - started, 3)
    result_queue.put(row)


def probe_url_isolated(url: str, timeout_seconds: int, wait_ms: int,
                       browser_proxy: str | None, hard_timeout_seconds: int) -> dict:
    context = mp.get_context("spawn")
    result_queue = context.Queue(maxsize=1)
    process = context.Process(
        target=probe_url_worker,
        args=(result_queue, url, timeout_seconds, wait_ms, browser_proxy),
    )
    started = time.monotonic()
    process.start()
    process.join(hard_timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join()
        return {
            "status": "timeout", "url": url, "error_type": "hard_timeout",
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    try:
        return result_queue.get(timeout=1)
    except queue.Empty:
        return {
            "status": "error", "url": url, "error_type": "worker_no_result",
            "worker_exit_code": process.exitcode,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }


def probe_many(urls: list[str], probe_fn, workers: int):
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(probe_fn, url): url for url in urls}
        for future in as_completed(futures):
            try:
                yield future.result()
            except Exception as exc:
                yield {
                    "status": "error", "url": futures[future],
                    "error_type": type(exc).__name__, "error": str(exc)[:1000],
                }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--urls", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--timeout-seconds", type=int, default=45)
    parser.add_argument("--wait-ms", type=int, default=1500)
    parser.add_argument("--hard-timeout-seconds", type=int, default=40)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--browser-proxy")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    completed = set()
    if args.output.exists():
        for line in args.output.read_text(encoding="utf-8").splitlines():
            if line.strip():
                completed.add(json.loads(line)["url"])
    urls = [line.strip() for line in args.urls.read_text(encoding="utf-8").splitlines() if line.strip()]

    pending = [url for url in urls[:args.limit] if url not in completed]
    probe_fn = functools.partial(
        probe_url_isolated,
        timeout_seconds=args.timeout_seconds,
        wait_ms=args.wait_ms,
        browser_proxy=args.browser_proxy,
        hard_timeout_seconds=args.hard_timeout_seconds,
    )
    for row in probe_many(pending, probe_fn, args.workers):
        append_jsonl(args.output, row)
        print(json.dumps(row, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
