"""Real-browser observation and declarative verification for Edit production."""

from __future__ import annotations

from contextlib import contextmanager
from functools import partial
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from typing import Any, Iterator
from urllib.parse import urlparse

from playwright.sync_api import Browser, BrowserContext, Page, Error as BrowserError, sync_playwright

from inspiration_library.production import (
    validate_browser_checks,
    validate_source_gap_checks,
)


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: Any) -> None:
        return


@contextmanager
def serve_project(project: Path) -> Iterator[str]:
    project = project.resolve()
    if not project.is_dir() or not (project / "index.html").is_file():
        raise FileNotFoundError(f"project requires index.html: {project}")
    handler = partial(_QuietHandler, directory=str(project))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _launch_browser(playwright: Any, *, proxy: str | None = None) -> Browser:
    options = {"proxy": {"server": proxy}} if proxy else {}
    if proxy == "direct://":
        options = {"args": ["--no-proxy-server"]}
    executable = Path(playwright.chromium.executable_path)
    if executable.is_file():
        return playwright.chromium.launch(headless=True, **options)
    return playwright.chromium.launch(channel="chrome", headless=True, **options)


def _request_url_without_query(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(query="", fragment="").geturl()


def _network_guard(
    page: Page,
    remote_requests: list[str],
    *,
    network_mode: str = "local_only",
    entry_url: str | None = None,
) -> None:
    if network_mode not in {"local_only", "online_readonly"}:
        raise ValueError(f"unsupported network mode: {network_mode}")
    entry = urlparse(entry_url or "")
    entry_origin = (entry.scheme, entry.hostname, entry.port)

    def intercept(route: Any) -> None:
        request = route.request
        parsed = urlparse(request.url)
        if parsed.scheme in {"data", "blob"} or parsed.hostname in {
            "127.0.0.1",
            "localhost",
        }:
            route.continue_()
            return
        remote_requests.append(_request_url_without_query(request.url))
        if network_mode == "local_only":
            route.abort()
            return
        request_origin = (parsed.scheme, parsed.hostname, parsed.port)
        if request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            route.abort()
            return
        if request.is_navigation_request() and request_origin != entry_origin:
            route.abort()
            return
        route.continue_()

    page.route("**/*", intercept)


def _new_page(
    browser: Browser,
    *,
    viewport: dict[str, int],
    remote_requests: list[str],
    console_errors: list[str],
    page_errors: list[str],
    dialog_events: list[dict[str, str]] | None = None,
    network_mode: str = "local_only",
    entry_url: str | None = None,
) -> tuple[BrowserContext, Page]:
    context = browser.new_context(viewport=viewport)
    from inspiration_library.component_closure import EVENT_RECORDER
    context.add_init_script(EVENT_RECORDER)
    if network_mode == "online_readonly":
        context.add_init_script("""(() => {
          document.addEventListener('submit', event => { event.preventDefault(); event.stopImmediatePropagation(); }, true);
          for (const name of ['submit', 'requestSubmit']) {
            Object.defineProperty(HTMLFormElement.prototype, name, {
              value: function(){}, configurable: false, writable: false
            });
          }
        })();""")
    page = context.new_page()
    page.set_default_timeout(5_000)
    _network_guard(
        page,
        remote_requests,
        network_mode=network_mode,
        entry_url=entry_url,
    )
    page.on(
        "console",
        lambda message: console_errors.append(message.text)
        if message.type == "error"
        else None,
    )
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    if dialog_events is not None:
        def capture_dialog(dialog: Any) -> None:
            dialog_events.append({"type": dialog.type, "message": dialog.message})
            dialog.dismiss()

        page.on("dialog", capture_dialog)
    return context, page


def _settle_online_page(page: Page, ready_selector: str | None) -> None:
    """Wait for real page readiness, not a fixed hope: load event, optional target, short quiet."""
    try:
        page.wait_for_load_state("load", timeout=15_000)
    except Exception:
        pass
    page.wait_for_timeout(500)
    if ready_selector:
        page.locator(ready_selector).first.wait_for(state="visible", timeout=15_000)


def _capture_screenshot(page: Page, path: Path, page_errors: list[str], *, full_page=True) -> None:
    try:
        page.screenshot(path=str(path), full_page=full_page, timeout=30_000)
    except Exception as exc:
        page_errors.append(f"screenshot: {type(exc).__name__}: {exc}")


def _snapshot(page: Page, *, _frame_depth: int = 0) -> dict[str, Any]:
    page.locator("body").wait_for(state="attached", timeout=5_000)
    payload = page.evaluate(
        r"""() => {
          const esc = (value) => CSS.escape(String(value));
          const selectorFor = (el) => {
            const scope = el.getRootNode();
            if (scope instanceof ShadowRoot) {
              const local = el.id ? `#${esc(el.id)}` : (() => {
                const parts=[];
                for(let node=el; node && node !== scope; node=node.parentNode) {
                  if (!(node instanceof Element)) break;
                  const siblings=[...node.parentNode.children].filter(s=>s.tagName===node.tagName);
                  parts.unshift(`${node.localName}:nth-of-type(${siblings.indexOf(node)+1})`);
                }
                return parts.join(' > ');
              })();
              return selectorFor(scope.host) + ' ::shadow:: ' + local;
            }
            if (el.id) return `#${esc(el.id)}`;
            const preferredAttrs = ['data-testid', 'data-test', 'data-select-batch',
                                    'data-record-id', 'data-project-id', 'data-route', 'name',
                                    'href', 'onclick'];
            for (const attr of preferredAttrs) {
              const value = el.getAttribute(attr);
              if (value && document.querySelectorAll(`[${attr}="${esc(value)}"]`).length === 1) {
                return `[${attr}="${esc(value)}"]`;
              }
            }
            const parts = [];
            let node = el;
            while (node && node.nodeType === Node.ELEMENT_NODE && node !== document.documentElement) {
              if (node.id) {
                parts.unshift(`#${esc(node.id)}`);
                break;
              }
              const tag = node.tagName.toLowerCase();
              const sameTagSiblings = node.parentElement
                ? [...node.parentElement.children].filter((sibling) => sibling.tagName === node.tagName)
                : [node];
              const part = sameTagSiblings.length > 1
                ? `${tag}:nth-of-type(${sameTagSiblings.indexOf(node) + 1})`
                : tag;
              parts.unshift(part);
              const candidate = parts.join(' > ');
              if (document.querySelectorAll(candidate).length === 1) return candidate;
              node = node.parentElement;
            }
            return parts.join(' > ');
          };
          const recorder = window.__componentClosureRecorder;
          const eventTypes = new Map();
          for (const record of recorder?.records || []) {
            const targets=[];
            if (record.target instanceof Element && record.target.isConnected) targets.push(record.target);
            if (record.target === document || record.target === window) {
              for(const match of record.source.matchAll(/\.(?:matches|closest|querySelector|querySelectorAll)\(\s*(['"])(.*?)\1/g)) {
                try { targets.push(...document.querySelectorAll(match[2])); } catch (_) {}
              }
            }
            for (const target of targets) {
              if (!eventTypes.has(target)) eventTypes.set(target, new Set());
              eventTypes.get(target).add(record.type);
            }
          }
          const controlSelector =
            'button,input,select,textarea,a[href],[role="button"],[role="tab"],'
            + '[contenteditable="true"],[draggable="true"],[tabindex]:not([tabindex="-1"]),[onclick],[onmouseover],[onmouseenter]';
          const interactive = [...new Set([
            ...(recorder?.elements() || document.querySelectorAll('*')),
          ])].filter(el => el.matches(controlSelector) || eventTypes.has(el)).map((el) => {
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            const componentRegion = el.closest(
              '[data-demo],[data-preview],[data-example],[class*="demo"],[class*="preview"],'
              + '[class*="example"],[class*="playground"],form,[role="tablist"],[role="tabpanel"],'
              + '[role="listbox"],[role="menu"],[role="dialog"],table'
            );
            const contentRegion = componentRegion || el.closest('section,article,main,[role="main"]') || el.parentElement;
            return {
              selector: selectorFor(el),
              event_types: [...new Set([...(eventTypes.get(el) || []),
                ...[...el.attributes].filter(attr=>attr.name.startsWith('on')).map(attr=>attr.name.slice(2))])],
              discovery_source: eventTypes.has(el) ? 'registered_event_listener' : 'dom',
              shadow_mode: el.getRootNode() instanceof ShadowRoot ? el.getRootNode().mode : null,
              expanded: el.getAttribute('aria-expanded'),
              selected: el.getAttribute('aria-selected'),
              sort: el.getAttribute('aria-sort'),
              tag: el.tagName.toLowerCase(),
              role: el.getAttribute('role') || '',
              type: el.getAttribute('type') || '',
              name: el.getAttribute('name') || '',
              aria_label: el.getAttribute('aria-label') || '',
              href: el.getAttribute('href') || '',
              data_action: el.getAttribute('data-action') || '',
              data_command: el.getAttribute('data-cmd') || '',
              in_main: Boolean(el.closest('main,[role="main"],article')),
              in_component: Boolean(componentRegion),
              in_header: Boolean(el.closest('header')),
              in_nav: Boolean(el.closest('nav')),
              in_aside: Boolean(el.closest('aside')),
              in_footer: Boolean(el.closest('footer')),
              in_code_region: Boolean(el.closest('pre,code,[data-code]')),
              in_table: Boolean(el.closest('table')),
              region_text: String(contentRegion?.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 500),
              text: String(el.innerText || el.value || '').trim(),
              value: 'value' in el ? String(el.value) : '',
              checked: 'checked' in el ? Boolean(el.checked) : null,
              disabled: 'disabled' in el ? Boolean(el.disabled) : null,
              readonly: 'readOnly' in el ? Boolean(el.readOnly) : false,
              visible: rect.width > 0 && rect.height > 0
                && style.display !== 'none' && style.visibility !== 'hidden',
              horizontally_reachable: rect.right > 0 && rect.left < window.innerWidth,
              draggable: el.getAttribute('draggable') === 'true',
              tabindex: el.getAttribute('tabindex'),
              title: el.getAttribute('title') || '',
              options: el.tagName === 'SELECT'
                ? [...el.options].map((option) => ({value: option.value, text: option.text}))
                : [],
            };
          });
          const structures = [...document.querySelectorAll(
            'header,nav,main,aside,footer,form,table,ul,ol,canvas,svg,[role]'
          )].map((el) => ({
            tag: el.tagName.toLowerCase(),
            id: el.id || '',
            role: el.getAttribute('role') || '',
            aria_label: el.getAttribute('aria-label') || '',
            child_count: el.children.length,
            text: (el.innerText || '').trim(),
          }));
          const visualSurfaces = [...document.querySelectorAll('canvas,svg')]
            .map((el) => {
              const rect = el.getBoundingClientRect();
              return {
                selector: selectorFor(el),
                tag: el.tagName.toLowerCase(),
                role: el.getAttribute('role') || '',
                aria_label: el.getAttribute('aria-label') || '',
                width: Math.round(rect.width),
                height: Math.round(rect.height),
                child_count: el.children.length,
                view_box: el.getAttribute('viewBox') || '',
                visible: rect.width > 0 && rect.height > 0,
              };
            });
          const styleSamples = [...document.querySelectorAll(
            'body,header,nav,main,aside,section,article,footer,form,button,input,select,textarea,[role="dialog"]'
          )].map((el) => {
            const style = getComputedStyle(el);
            return {
              selector: selectorFor(el),
              tag: el.tagName.toLowerCase(),
              role: el.getAttribute('role') || '',
              font_family: style.fontFamily,
              font_size: style.fontSize,
              font_weight: style.fontWeight,
              color: style.color,
              background_color: style.backgroundColor,
              border_radius: style.borderRadius,
              border_width: style.borderWidth,
              box_shadow: style.boxShadow,
              letter_spacing: style.letterSpacing,
            };
          });
          const local = Object.fromEntries(
            Array.from({length: localStorage.length}, (_, index) => localStorage.key(index))
              .filter(Boolean).map((key) => [key, localStorage.getItem(key)])
          );
          const session = Object.fromEntries(
            Array.from({length: sessionStorage.length}, (_, index) => sessionStorage.key(index))
              .filter(Boolean).map((key) => [key, sessionStorage.getItem(key)])
          );
          const landmarkLayouts = [...document.querySelectorAll(
            'header,nav,main,aside,footer,form,table,[role="dialog"],[role="grid"],section'
          )].map((el) => {
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return {
              selector: selectorFor(el),
              tag: el.tagName.toLowerCase(),
              role: el.getAttribute('role') || '',
              display: style.display,
              position: style.position,
              overflow_x: style.overflowX,
              overflow_y: style.overflowY,
              grid_columns: style.gridTemplateColumns,
              flex_direction: style.flexDirection,
              width: Math.round(rect.width),
              height: Math.round(rect.height),
              x: Math.round(rect.x),
              y: Math.round(rect.y),
            };
          });
          const ariaStates = [...document.querySelectorAll(
            '[aria-expanded],[aria-selected],[aria-checked],[aria-invalid],[aria-live],[aria-current],[aria-disabled]'
          )].map((el) => ({
            selector: selectorFor(el),
            aria_expanded: el.getAttribute('aria-expanded'),
            aria_selected: el.getAttribute('aria-selected'),
            aria_checked: el.getAttribute('aria-checked'),
            aria_invalid: el.getAttribute('aria-invalid'),
            aria_live: el.getAttribute('aria-live'),
            aria_current: el.getAttribute('aria-current'),
            aria_disabled: el.getAttribute('aria-disabled'),
          }));
          const focusableOrder = [...document.querySelectorAll(
            'button,input,select,textarea,a[href],[tabindex],[contenteditable="true"]'
          )].filter((el) => {
            const style = getComputedStyle(el);
            return !el.disabled && style.display !== 'none' && style.visibility !== 'hidden';
          }).map((el) => ({
            selector: selectorFor(el),
            tag: el.tagName.toLowerCase(),
            role: el.getAttribute('role') || '',
            tabindex: el.getAttribute('tabindex'),
            text: String(el.innerText || el.value || el.getAttribute('aria-label') || '').trim(),
          }));
          const active = document.activeElement;
          const activeRect = active && active.getBoundingClientRect
            ? active.getBoundingClientRect()
            : null;
          const activeElement = active && active.nodeType === Node.ELEMENT_NODE
            ? {
                selector: selectorFor(active),
                tag: active.tagName.toLowerCase(),
                role: active.getAttribute('role') || '',
                type: active.getAttribute('type') || '',
                aria_label: active.getAttribute('aria-label') || '',
                text: String(active.innerText || active.value || '').trim(),
                contenteditable: active.getAttribute('contenteditable') || '',
                rect: activeRect ? {
                  x: Math.round(activeRect.x),
                  y: Math.round(activeRect.y),
                  width: Math.round(activeRect.width),
                  height: Math.round(activeRect.height),
                } : null,
              }
            : null;
          const recordCandidates = [...document.querySelectorAll(
            'article,tbody > tr,[role="row"],[data-item-id],[data-record-id],'
            + '[data-post-id],[data-product-id],[data-user-id],[data-card-id]'
          )].filter((el) => {
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            return rect.width > 0 && rect.height > 0
              && style.display !== 'none' && style.visibility !== 'hidden'
              && (el.innerText || '').trim();
          });
          const recordGroupsByKey = new Map();
          for (const el of recordCandidates) {
            const parent = el.parentElement;
            if (!parent) continue;
            const classSignature = [...el.classList].sort().join('.');
            const key = [
              selectorFor(parent),
              el.tagName.toLowerCase(),
              el.getAttribute('role') || '',
              classSignature,
            ].join('|');
            if (!recordGroupsByKey.has(key)) {
              recordGroupsByKey.set(key, {
                parent_selector: selectorFor(parent),
                item_tag: el.tagName.toLowerCase(),
                item_role: el.getAttribute('role') || '',
                item_class_signature: classSignature,
                records: [],
              });
            }
            const ownData = {};
            for (const attr of [...el.attributes]) {
              if (attr.name.startsWith('data-') && attr.value) {
                ownData[attr.name] = attr.value;
              }
            }
            const markerNodes = [...el.querySelectorAll(
              '[class*="tag" i],[class*="badge" i],[class*="chip" i],'
              + '[class*="status" i],[class*="category" i],[class*="role" i],'
              + '[data-tag],[data-category],[data-status],[data-type]'
            )];
            const markerFields = markerNodes.map((node) => ({
              selector: selectorFor(node),
              text: (node.innerText || node.getAttribute('aria-label') || '').trim(),
              data: Object.fromEntries(
                [...node.attributes]
                  .filter((attr) => attr.name.startsWith('data-') && attr.value)
                  .map((attr) => [attr.name, attr.value])
              ),
            })).filter((row) => row.text || Object.keys(row.data).length);
            recordGroupsByKey.get(key).records.push({
              selector: selectorFor(el),
              text: (el.innerText || '').trim(),
              data: ownData,
              marker_fields: markerFields,
            });
          }
          const recordGroups = [...recordGroupsByKey.values()]
            .filter((group) => group.records.length >= 2)
            .map((group) => ({...group, item_count: group.records.length}));
          const rootStyle = getComputedStyle(document.documentElement);
          const rootCssVariables = {};
          for (const name of [...rootStyle].filter((item) => item.startsWith('--'))) {
            rootCssVariables[name] = rootStyle.getPropertyValue(name).trim();
          }
          const outerHtml = document.documentElement.outerHTML;
          return {
            title: document.title,
            url: location.href,
            visible_text: (document.body.innerText || '').trim(),
            html: outerHtml,
            html_length: outerHtml.length,
            html_truncated: false,
            interactive,
            embedded_documents: [...document.querySelectorAll('iframe[src]')]
              .filter(el => { const r = el.getBoundingClientRect();
                return /^https?:/.test(el.src) && r.width >= 32 && r.height >= 32
                  && getComputedStyle(el).visibility !== 'hidden'; })
              .slice(0, 8).map(el => ({url:el.src, selector:selectorFor(el),
                title:el.title || '', same_origin:new URL(el.src).origin === location.origin})),
            structures,
            visual_surfaces: visualSurfaces,
            style_samples: styleSamples,
            viewport: {width: window.innerWidth, height: window.innerHeight},
            landmark_layouts: landmarkLayouts,
            aria_states: ariaStates,
            focusable_order: focusableOrder,
            active_element: activeElement,
            scroll_position: {
              x: Math.round(window.scrollX),
              y: Math.round(window.scrollY),
              max_x: Math.max(0, Math.round(document.documentElement.scrollWidth - window.innerWidth)),
              max_y: Math.max(0, Math.round(document.documentElement.scrollHeight - window.innerHeight)),
            },
            record_groups: recordGroups,
            root_css_variables: rootCssVariables,
            local_storage: local,
            session_storage: session,
            horizontal_overflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
            body_size: {
              scroll_width: document.documentElement.scrollWidth,
              client_width: document.documentElement.clientWidth,
              scroll_height: document.documentElement.scrollHeight,
            },
          };
        }"""
    )
    payload["html"] = page.evaluate("() => window.__componentClosureRecorder?.serialize(document.documentElement).outerHTML || document.documentElement.outerHTML")
    payload["frame_snapshots"] = {}
    if _frame_depth < 2:
        frame_owner = getattr(page, "main_frame", page)
        for frame in frame_owner.child_frames[:8]:
            try:
                element = frame.frame_element()
                if not element.is_visible():
                    continue
                selector = element.evaluate("""el => {
                  if (el.id) return '#' + CSS.escape(el.id);
                  const parts=[];
                  for(let node=el; node && node!==document.documentElement; node=node.parentElement){
                    const siblings=[...node.parentElement.children].filter(s=>s.tagName===node.tagName);
                    parts.unshift(node.localName+':nth-of-type('+(siblings.indexOf(node)+1)+')');
                  }
                  return parts.join(' > ');
                }""")
                snapshot = _snapshot(frame, _frame_depth=_frame_depth + 1)
                payload["frame_snapshots"][selector] = snapshot
                payload["interactive"].extend({**row, "selector": selector + " ::frame:: " + row["selector"]}
                                              for row in snapshot["interactive"])
            except Exception as exc:
                payload.setdefault("frame_errors", []).append(str(exc))
    try:
        payload["aria_snapshot"] = page.locator("body").aria_snapshot(timeout=5_000)
    except Exception as exc:  # Playwright builds before aria_snapshot remain usable.
        payload["aria_snapshot"] = None
        payload["aria_snapshot_error"] = f"{type(exc).__name__}: {exc}"
    signature_source = json.dumps(
        {
            "url": payload["url"],
            "visible_text": payload["visible_text"],
            "interactive": payload["interactive"],
            "visual_surfaces": payload["visual_surfaces"],
            "style_samples": payload["style_samples"],
            "local_storage": payload["local_storage"],
            "session_storage": payload["session_storage"],
            "viewport": payload["viewport"],
            "landmark_layouts": payload["landmark_layouts"],
            "aria_states": payload["aria_states"],
            "active_element": payload["active_element"],
            "scroll_position": payload["scroll_position"],
            "record_groups": payload["record_groups"],
            "root_css_variables": payload["root_css_variables"],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    payload["state_sha256"] = sha256(signature_source.encode("utf-8")).hexdigest()
    return payload


def dom_ax_state_records(observation: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten saved browser snapshots into de-duplicated DOM/AX state rows."""

    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(state_id: str, snapshot: Any, *, action: Any = None) -> None:
        if not isinstance(snapshot, dict):
            return
        signature = str(snapshot.get("state_sha256") or state_id)
        if signature in seen:
            return
        seen.add(signature)
        records.append(
            {
                "state_id": state_id,
                "state_sha256": snapshot.get("state_sha256"),
                "url": snapshot.get("url"),
                "title": snapshot.get("title"),
                "action": action,
                "dom_html": snapshot.get("html", ""),
                "dom_html_length": snapshot.get("html_length"),
                "dom_html_truncated": snapshot.get("html_truncated", False),
                "aria_snapshot": snapshot.get("aria_snapshot"),
                "visible_text": snapshot.get("visible_text"),
                "interactive": snapshot.get("interactive", []),
                "active_element": snapshot.get("active_element"),
                "scroll_position": snapshot.get("scroll_position", {}),
                "record_groups": snapshot.get("record_groups", []),
                "local_storage": snapshot.get("local_storage", {}),
                "session_storage": snapshot.get("session_storage", {}),
            }
        )

    add("baseline", observation.get("baseline"))
    add("mobile_baseline", observation.get("mobile_baseline"))
    for path in observation.get("exploration_paths", []):
        if not isinstance(path, dict):
            continue
        path_id = str(path.get("id", "path"))
        add(f"{path_id}__before", path.get("before"))
        for index, step in enumerate(path.get("steps", []), 1):
            if isinstance(step, dict):
                add(
                    f"{path_id}__step_{index}",
                    step.get("state"),
                    action=step.get("action"),
                )
        add(f"{path_id}__after", path.get("after"))
    return records


def _visual_routing(
    baseline: dict[str, Any],
    mobile_baseline: dict[str, Any],
    paths: list[dict[str, Any]],
) -> dict[str, Any]:
    states: list[tuple[str, dict[str, Any]]] = [
        ("baseline", baseline),
        ("mobile_baseline", mobile_baseline),
    ]
    for path in paths:
        path_id = str(path.get("id", "path"))
        for index, step in enumerate(path.get("steps", []), 1):
            if isinstance(step, dict) and isinstance(step.get("state"), dict):
                states.append((f"{path_id}__step_{index}", step["state"]))
    all_rows: list[dict[str, Any]] = []
    large_rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for state_id, snapshot in states:
        for surface in snapshot.get("visual_surfaces", []):
            if not isinstance(surface, dict) or not surface.get("visible"):
                continue
            key = (str(surface.get("tag")), str(surface.get("selector")))
            if key in seen:
                continue
            seen.add(key)
            row = {"state_id": state_id, **surface}
            all_rows.append(row)
            width = int(surface.get("width") or 0)
            height = int(surface.get("height") or 0)
            if surface.get("tag") == "canvas" or (
                surface.get("tag") == "svg"
                and width >= 240
                and height >= 120
            ):
                large_rows.append(row)
    return {
        "needs_visual_interpretation": bool(large_rows),
        "visible_visual_surface_count": len(all_rows),
        "large_visual_surface_count": len(large_rows),
        "large_visual_surfaces": large_rows,
        "policy": "route_large_canvas_or_svg_states_to_visual_inspection",
    }


def _write_dom_ax_states(output_dir: Path, observation: dict[str, Any]) -> None:
    rows = dom_ax_state_records(observation)
    rendered = "".join(
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
        for row in rows
    )
    (output_dir / "dom_ax_states.jsonl").write_text(rendered, encoding="utf-8")


def _selector_scope(page, selector):
    parts = selector.split(" ::frame:: ")
    for owner in parts[:-1]:
        element = page.locator(owner).element_handle()
        page = element.content_frame() if element else None
        if page is None:
            raise ValueError(f"frame unavailable: {owner}")
    return page, parts[-1]


def _action_target(page, selector):
    scope, selector = _selector_scope(page, selector)
    if " ::shadow:: " not in selector:
        return scope.locator(selector)
    handle = scope.evaluate_handle("""selector => {
      const parts = selector.split(' ::shadow:: ');
      let root=document;
      for (const part of parts.slice(0,-1)) {
        const host=root.querySelector(part);
        root=host && window.__componentClosureRecorder?.shadowFor(host);
        if (!root) return null;
      }
      return root.querySelector(parts.at(-1));
    }""", selector).as_element()
    if handle is None:
        raise ValueError(f"shadow target unavailable: {selector}")
    return handle


def _perform_action(page: Page, action: dict[str, Any]) -> Any:
    kind = action["action"]
    target = _action_target(page, action["selector"]) if action.get("selector") else None
    if kind == "click":
        target.click()
        result: Any = "clicked"
    elif kind == "fill":
        target.fill(str(action["value"]))
        result = "filled"
    elif kind == "drag_to":
        target.drag_to(
            _action_target(page, action["target_selector"])
        )
        result = "dragged"
    elif kind == "hover":
        target.hover()
        result = "hovered"
    elif kind == "select_option":
        target.select_option(str(action["value"]))
        result = "selected"
    elif kind == "check":
        target.check()
        result = "checked"
    elif kind == "uncheck":
        target.uncheck()
        result = "unchecked"
    elif kind == "key_press":
        locator = target
        locator.press(str(action["key"]))
        result = "pressed"
    elif kind == "reload":
        page.reload(wait_until="networkidle", timeout=30_000)
        result = "reloaded"
    elif kind == "scroll_into_view":
        target.scroll_into_view_if_needed()
        result = "scrolled"
    elif kind == "wait":
        milliseconds = int(action.get("milliseconds", 200))
        page.wait_for_timeout(milliseconds)
        result = milliseconds
    else:  # pragma: no cover - validation rejects this before execution.
        raise ValueError(f"unsupported browser action: {kind}")
    if kind not in {"wait", "reload"}:
        page.wait_for_timeout(400)
    return result


def _observe_entry_url(
    entry_url: str,
    output_dir: Path,
    *,
    exploration_plan: dict[str, Any] | None = None,
    network_mode: str,
    source_metadata: dict[str, Any],
    ready_selector: str | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    remote: list[str] = []
    console_errors: list[str] = []
    page_errors: list[str] = []
    dialog_events: list[dict[str, str]] = []
    with sync_playwright() as playwright:
        browser = (_launch_browser(playwright, proxy="direct://")
                   if network_mode == "online_readonly" else _launch_browser(playwright))
        try:
            context, page = _new_page(
                browser,
                viewport={"width": 1440, "height": 1000},
                remote_requests=remote,
                console_errors=console_errors,
                page_errors=page_errors,
                dialog_events=dialog_events,
                network_mode=network_mode,
                entry_url=entry_url,
            )
            try:
                try:
                    response = page.goto(
                        entry_url,
                        wait_until="domcontentloaded" if network_mode == "online_readonly" else "networkidle",
                        timeout=30_000,
                    )
                    if network_mode == "online_readonly" and response and response.status >= 400:
                        raise BrowserError(f"entry HTTP {response.status}")
                    if network_mode == "online_readonly":
                        print("entry_access: direct", flush=True)
                except Exception as exc:
                    proxy = os.environ.get("WEBCODING_BROWSER_PROXY")
                    if network_mode != "online_readonly" or not proxy:
                        raise
                    print(f"entry_access: direct failed ({type(exc).__name__}: {exc}); trying proxy", flush=True)
                    context.close()
                    browser.close()
                    browser = _launch_browser(playwright, proxy=proxy)
                    context, page = _new_page(
                        browser, viewport={"width": 1440, "height": 1000},
                        remote_requests=remote, console_errors=console_errors,
                        page_errors=page_errors, dialog_events=dialog_events,
                        network_mode=network_mode, entry_url=entry_url,
                    )
                    response = page.goto(entry_url, wait_until="domcontentloaded", timeout=30_000)
                    if response and response.status >= 400:
                        raise BrowserError(f"entry HTTP {response.status}")
                    print("entry_access: proxy", flush=True)
                if network_mode == "online_readonly":
                    _settle_online_page(page, ready_selector)
                baseline = _snapshot(page)
                _capture_screenshot(page, output_dir / "baseline.png", page_errors,
                                    full_page=network_mode != "online_readonly")
                if (output_dir / "baseline.png").is_file():
                    baseline["screenshot_path"] = str((output_dir / "baseline.png").resolve())
            finally:
                context.close()

            # Mobile layout is useful once at baseline. Repeating it for every
            # desktop interaction plan adds a full navigation without new action evidence.
            mobile_context, mobile_page = (None, None)
            if exploration_plan is None:
                mobile_context, mobile_page = _new_page(
                browser,
                viewport={"width": 390, "height": 844},
                remote_requests=remote,
                console_errors=console_errors,
                page_errors=page_errors,
                dialog_events=dialog_events,
                network_mode=network_mode,
                entry_url=entry_url,
            )
            try:
                if mobile_page is None:
                    mobile_baseline = {}
                else:
                    mobile_page.goto(
                    entry_url,
                    wait_until=(
                        "domcontentloaded"
                        if network_mode == "online_readonly"
                        else "networkidle"
                    ),
                    timeout=30_000,
                )
                    if network_mode == "online_readonly":
                        _settle_online_page(mobile_page, ready_selector)
                    mobile_baseline = _snapshot(mobile_page)
                    _capture_screenshot(
                        mobile_page,
                        output_dir / "baseline_mobile.png",
                        page_errors,
                        full_page=network_mode != "online_readonly",
                    )
                    if (output_dir / "baseline_mobile.png").is_file():
                        mobile_baseline["screenshot_path"] = str((output_dir / "baseline_mobile.png").resolve())
            except Exception as exc:
                if network_mode != "online_readonly":
                    raise
                mobile_baseline = {}
                page_errors.append(f"mobile_observation: {type(exc).__name__}: {exc}")
            finally:
                if mobile_context is not None:
                    mobile_context.close()

            paths: list[dict[str, Any]] = []
            for item in (exploration_plan or {}).get("paths", []):
                context, page = _new_page(
                    browser,
                    viewport={"width": 1440, "height": 1000},
                    remote_requests=remote,
                    console_errors=console_errors,
                    page_errors=page_errors,
                    dialog_events=dialog_events,
                    network_mode=network_mode,
                    entry_url=entry_url,
                )
                steps: list[dict[str, Any]] = []
                try:
                    page.goto(
                        entry_url,
                        wait_until=(
                            "domcontentloaded"
                            if network_mode == "online_readonly"
                            else "networkidle"
                        ),
                        timeout=30_000,
                    )
                    if network_mode == "online_readonly":
                        _settle_online_page(page, ready_selector)
                    before = _snapshot(page)
                    if network_mode == "online_readonly":
                        shot = output_dir / f"explore_{item['id']}__before.png"
                        _capture_screenshot(page, shot, page_errors, full_page=False)
                        if shot.is_file():
                            before["screenshot_path"] = str(shot.resolve())
                    status = "ok"
                    for action in item["actions"]:
                        step = {"action": action}
                        dialog_offset = len(dialog_events)
                        try:
                            step["output"] = _perform_action(page, action)
                            step["state"] = _snapshot(page)
                            if network_mode == "online_readonly":
                                shot = output_dir / f"explore_{item['id']}__step_{len(steps)+1}.png"
                                _capture_screenshot(page, shot, page_errors, full_page=False)
                                if shot.is_file():
                                    step["state"]["screenshot_path"] = str(shot.resolve())
                            step["dialogs"] = dialog_events[dialog_offset:]
                            step["status"] = "ok"
                        except Exception as exc:
                            step["status"] = "error"
                            step["error"] = f"{type(exc).__name__}: {exc}"
                            status = "error"
                            steps.append(step)
                            break
                        steps.append(step)
                    after = _snapshot(page)
                    _capture_screenshot(
                        page,
                        output_dir / f"explore_{item['id']}.png",
                        page_errors,
                    )
                    paths.append(
                        {
                            "id": item["id"],
                            "purpose": item.get("purpose", ""),
                            "status": status,
                            "before": before,
                            "steps": steps,
                            "after": after,
                            "state_changed": before["state_sha256"] != after["state_sha256"],
                        }
                    )
                except Exception as exc:
                    if network_mode != "online_readonly":
                        raise
                    paths.append({"id": item["id"], "purpose": item.get("purpose", ""),
                                  "status": "error", "steps": steps,
                                  "error": f"{type(exc).__name__}: {exc}", "state_changed": False})
                finally:
                    context.close()
        finally:
            browser.close()
    result = {
        "schema_version": "webcoding-browser-observation-v2",
        "status": (
            ("partial" if not mobile_baseline or any(path.get("status") != "ok" for path in paths) else "ok")
            if network_mode == "online_readonly"
            else "ok" if not remote and not console_errors and not page_errors else "error"
        ),
        **source_metadata,
        "entry_url": entry_url,
        "admission_status": "available_observation",
        "target_behavior_status": "not_verified",
        "baseline": baseline,
        "mobile_baseline": mobile_baseline,
        "exploration_paths": paths,
        "remote_requests": sorted(set(remote)),
        "console_errors": console_errors,
        "page_errors": page_errors,
        "dialog_events": dialog_events,
        "visual_routing": _visual_routing(baseline, mobile_baseline, paths),
    }
    (output_dir / "observation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_dom_ax_states(output_dir, result)
    return result


def observe_project(
    project: Path,
    output_dir: Path,
    *,
    exploration_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project = project.resolve()
    with serve_project(project) as entry_url:
        return _observe_entry_url(
            entry_url,
            output_dir,
            exploration_plan=exploration_plan,
            network_mode="local_only",
            source_metadata={"source_kind": "local_project", "project": str(project)},
        )


def observe_url(
    entry_url: str,
    output_dir: Path,
    *,
    exploration_plan: dict[str, Any] | None = None,
    ready_selector: str | None = None,
) -> dict[str, Any]:
    """Observe one public page without materializing it as a local project."""

    parsed = urlparse(entry_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"online observation requires an http(s) URL: {entry_url}")
    return _observe_entry_url(
        entry_url,
        output_dir,
        exploration_plan=exploration_plan,
        network_mode="online_readonly",
        source_metadata={"source_kind": "live_url", "source_url": entry_url},
        ready_selector=ready_selector,
    )


def _assert(page: Page, assertion: dict[str, Any]) -> tuple[bool, Any]:
    kind = assertion["type"]
    if kind == "url_contains":
        actual: Any = page.url
        return str(assertion["value"]) in actual, actual
    if kind == "storage_json_contains":
        storage = assertion.get("storage", "local")
        expression = (
            "([store,key]) => window[store].getItem(key)"
        )
        actual = page.evaluate(
            expression,
            ["localStorage" if storage == "local" else "sessionStorage", assertion["key"]],
        )
        return str(assertion["value"]) in str(actual), actual
    locator = page.locator(assertion["selector"])
    if kind == "visible":
        actual = locator.is_visible()
        return bool(actual), actual
    if kind == "hidden":
        actual = locator.is_hidden()
        return bool(actual), actual
    if kind in {"count_equals", "count_at_least"}:
        actual = locator.count()
        expected = int(assertion["value"])
        return (actual == expected if kind == "count_equals" else actual >= expected), actual
    if kind in {"text_contains", "text_equals"}:
        actual = locator.inner_text()
        expected = str(assertion["value"])
        return (expected in actual if kind == "text_contains" else actual.strip() == expected), actual
    if kind == "attribute_equals":
        actual = locator.get_attribute(str(assertion["name"]))
        return actual == str(assertion["value"]), actual
    if kind == "property_equals":
        actual = locator.evaluate("(el, name) => el[name]", str(assertion["name"]))
        return actual == assertion["value"], actual
    raise ValueError(f"unsupported assertion: {kind}")


def verify_project(
    project: Path,
    checks: list[dict[str, Any]],
    output_dir: Path,
    *,
    label: str,
) -> dict[str, Any]:
    normalized = validate_browser_checks(checks)
    output_dir.mkdir(parents=True, exist_ok=True)
    remote: list[str] = []
    console_errors: list[str] = []
    page_errors: list[str] = []
    rows: list[dict[str, Any]] = []
    with serve_project(project) as url, sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        try:
            for check in normalized:
                context, page = _new_page(
                    browser,
                    viewport={"width": 1440, "height": 1000},
                    remote_requests=remote,
                    console_errors=console_errors,
                    page_errors=page_errors,
                )
                row: dict[str, Any] = {"id": check["id"], "actions": [], "assertions": []}
                try:
                    page.goto(url, wait_until="networkidle", timeout=30_000)
                    for action in check["actions"]:
                        action_row = {"action": action}
                        try:
                            action_row["output"] = _perform_action(page, action)
                            action_row["status"] = "ok"
                        except Exception as exc:
                            action_row.update(
                                {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
                            )
                        row["actions"].append(action_row)
                        if action_row["status"] != "ok":
                            break
                    if all(item["status"] == "ok" for item in row["actions"]):
                        for assertion in check["assertions"]:
                            assertion_row = {"assertion": assertion}
                            try:
                                passed, actual = _assert(page, assertion)
                                assertion_row.update(
                                    {"status": "ok" if passed else "failed", "actual": actual}
                                )
                            except Exception as exc:
                                assertion_row.update(
                                    {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
                                )
                            row["assertions"].append(assertion_row)
                    snapshot = _snapshot(page)
                    row["state_sha256"] = snapshot["state_sha256"]
                    row["horizontal_overflow"] = snapshot["horizontal_overflow"]
                    page.screenshot(
                        path=str(output_dir / f"{label}__{check['id']}.png"),
                        full_page=True,
                    )
                finally:
                    context.close()
                row["status"] = (
                    "ok"
                    if row["actions"]
                    and all(item["status"] == "ok" for item in row["actions"])
                    and row["assertions"]
                    and all(item["status"] == "ok" for item in row["assertions"])
                    and not row.get("horizontal_overflow")
                    else "error"
                )
                # Checks with no setup actions are valid regression observations.
                if not check["actions"] and row["assertions"] and all(
                    item["status"] == "ok" for item in row["assertions"]
                ) and not row.get("horizontal_overflow"):
                    row["status"] = "ok"
                rows.append(row)
        finally:
            browser.close()
    result = {
        "schema_version": "webcoding-browser-verification-v1",
        "status": "ok"
        if rows
        and all(row["status"] == "ok" for row in rows)
        and not remote
        and not console_errors
        and not page_errors
        else "error",
        "project": str(project.resolve()),
        "checks": rows,
        "remote_requests": sorted(set(remote)),
        "console_errors": console_errors,
        "page_errors": page_errors,
    }
    (output_dir / f"{label}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def verify_source_gap(
    project: Path,
    checks: list[dict[str, Any]],
    output_dir: Path,
    *,
    label: str,
) -> dict[str, Any]:
    """Require a positive capability check to fail on the current source.

    A confirmed gap means all existing-state setup actions succeeded and the
    capability portion or its assertions did not. If the entire positive check
    passes, the source already has the requested behavior.
    """

    normalized = validate_source_gap_checks(checks)
    browser_checks = [
        {
            "id": row["id"],
            "actions": row["actions"],
            "assertions": row["assertions"],
        }
        for row in normalized
    ]
    browser_result = verify_project(
        project,
        browser_checks,
        output_dir,
        label=label,
    )
    decisions: list[dict[str, Any]] = []
    for specification, execution in zip(
        normalized, browser_result["checks"], strict=True
    ):
        setup_count = specification["setup_action_count"]
        actions = execution.get("actions", [])
        setup_ok = len(actions) >= setup_count and all(
            row.get("status") == "ok" for row in actions[:setup_count]
        )
        capability_action_failed = any(
            row.get("status") != "ok" for row in actions[setup_count:]
        )
        assertion_failed = any(
            row.get("status") != "ok" for row in execution.get("assertions", [])
        )
        positive_check_passed = execution.get("status") == "ok"
        if not setup_ok:
            decision = "invalid_setup"
        elif positive_check_passed:
            decision = "already_present"
        elif capability_action_failed or assertion_failed:
            decision = "missing"
        else:
            decision = "invalid_check"
        decisions.append(
            {
                "id": specification["id"],
                "setup_action_count": setup_count,
                "setup_ok": setup_ok,
                "positive_check_passed": positive_check_passed,
                "decision": decision,
            }
        )
    environment_ok = not any(
        browser_result.get(key)
        for key in ("remote_requests", "console_errors", "page_errors")
    )
    if not environment_ok or any(
        row["decision"] in {"invalid_setup", "invalid_check"} for row in decisions
    ):
        status = "invalid_check"
    elif decisions and all(row["decision"] == "missing" for row in decisions):
        status = "gap_confirmed"
    else:
        status = "source_already_has_behavior"
    result = {
        "schema_version": "webcoding-source-gap-browser-check-v1",
        "status": status,
        "project": browser_result["project"],
        "checks": decisions,
        "browser_evidence": str((output_dir / f"{label}.json").resolve()),
        "remote_requests": browser_result["remote_requests"],
        "console_errors": browser_result["console_errors"],
        "page_errors": browser_result["page_errors"],
    }
    (output_dir / f"{label}__source_gap.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def verify_layouts(project: Path, output_dir: Path, *, label: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    remote: list[str] = []
    console_errors: list[str] = []
    page_errors: list[str] = []
    rows: list[dict[str, Any]] = []
    viewports = {
        "desktop": {"width": 1440, "height": 1000},
        "mobile": {"width": 390, "height": 844},
    }
    with serve_project(project) as url, sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        try:
            for viewport_id, viewport in viewports.items():
                context, page = _new_page(
                    browser,
                    viewport=viewport,
                    remote_requests=remote,
                    console_errors=console_errors,
                    page_errors=page_errors,
                )
                try:
                    page.goto(url, wait_until="networkidle", timeout=30_000)
                    snapshot = _snapshot(page)
                    page.screenshot(
                        path=str(output_dir / f"{label}__{viewport_id}.png"),
                        full_page=True,
                    )
                    rows.append(
                        {
                            "viewport": viewport_id,
                            "width": viewport["width"],
                            "height": viewport["height"],
                            "horizontal_overflow": snapshot["horizontal_overflow"],
                            "body_size": snapshot["body_size"],
                            "status": "ok" if not snapshot["horizontal_overflow"] else "error",
                        }
                    )
                finally:
                    context.close()
        finally:
            browser.close()
    result = {
        "schema_version": "webcoding-layout-verification-v1",
        "status": "ok"
        if rows
        and all(row["status"] == "ok" for row in rows)
        and not remote
        and not console_errors
        and not page_errors
        else "error",
        "project": str(project.resolve()),
        "viewports": rows,
        "remote_requests": sorted(set(remote)),
        "console_errors": console_errors,
        "page_errors": page_errors,
    }
    (output_dir / f"{label}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def _normalize_observation_probe(probe: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(probe, dict):
        raise ValueError(f"{label} must be an object")
    kind = probe.get("type")
    supported = {"text", "count", "attribute", "property", "visible", "url", "storage"}
    if kind not in supported:
        raise ValueError(f"{label} has unsupported type: {kind}")
    normalized: dict[str, Any] = {"type": kind}
    if kind not in {"url", "storage"}:
        selector = probe.get("selector")
        if not isinstance(selector, str) or not selector.strip():
            raise ValueError(f"{label}.selector must be a non-empty string")
        normalized["selector"] = selector.strip()
    if kind in {"attribute", "property"}:
        name = probe.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{label}.name must be a non-empty string")
        normalized["name"] = name.strip()
    if kind == "storage":
        storage = probe.get("storage", "local")
        if storage not in {"local", "session"}:
            raise ValueError(f"{label}.storage must be local or session")
        key = probe.get("key")
        if not isinstance(key, str) or not key.strip():
            raise ValueError(f"{label}.key must be a non-empty string")
        normalized.update({"storage": storage, "key": key.strip()})
    return normalized


def _read_observation_probe(page: Page, probe: dict[str, Any]) -> Any:
    kind = probe["type"]
    if kind == "url":
        return page.url
    if kind == "storage":
        storage_name = (
            "localStorage" if probe.get("storage", "local") == "local" else "sessionStorage"
        )
        return page.evaluate(
            "([store, key]) => window[store].getItem(key)",
            [storage_name, probe["key"]],
        )
    locator = page.locator(probe["selector"])
    if kind == "text":
        return locator.inner_text().strip()
    if kind == "count":
        return locator.count()
    if kind == "attribute":
        return locator.get_attribute(probe["name"])
    if kind == "property":
        return locator.evaluate("(el, name) => el[name]", probe["name"])
    if kind == "visible":
        return locator.is_visible()
    raise ValueError(f"unsupported observation probe: {kind}")


def run_dependency_intervention_probe(
    project: Path,
    check: dict[str, Any],
    output_dir: Path,
    *,
    label: str,
) -> dict[str, Any]:
    """Change a producer state several times and observe the consumer output.

    Cases run sequentially in one browser context, so a final restore case can
    return to the baseline after one or more interventions.  This function
    records observations only; ``certify_dependency`` combines them with
    source-gap, reverse-order, and regression evidence.
    """

    if not isinstance(check, dict):
        raise ValueError("dependency intervention check must be an object")
    check_id = check.get("id")
    if not isinstance(check_id, str) or not check_id.strip():
        raise ValueError("dependency intervention check requires an id")
    raw_cases = check.get("cases")
    if not isinstance(raw_cases, list) or not 3 <= len(raw_cases) <= 8:
        raise ValueError("dependency intervention check requires three to eight cases")
    normalized_checks = validate_browser_checks(
        [
            {
                "id": row.get("case_id") if isinstance(row, dict) else None,
                "actions": row.get("actions", []) if isinstance(row, dict) else None,
                "assertions": [{"type": "visible", "selector": "body"}],
            }
            for row in raw_cases
        ],
        max_checks=8,
    )
    producer_probe = _normalize_observation_probe(
        check.get("producer_probe"), label="producer_probe"
    )
    consumer_probe = _normalize_observation_probe(
        check.get("consumer_probe"), label="consumer_probe"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    remote: list[str] = []
    console_errors: list[str] = []
    page_errors: list[str] = []
    observations: list[dict[str, Any]] = []
    with serve_project(project) as url, sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        try:
            context, page = _new_page(
                browser,
                viewport={"width": 1440, "height": 1000},
                remote_requests=remote,
                console_errors=console_errors,
                page_errors=page_errors,
            )
            try:
                page.goto(url, wait_until="networkidle", timeout=30_000)
                for case in normalized_checks:
                    row: dict[str, Any] = {
                        "case_id": case["id"],
                        "actions": [],
                        "action_status": "ok",
                        "producer_observed": False,
                        "consumer_observed": False,
                    }
                    for action in case["actions"]:
                        action_row: dict[str, Any] = {"action": action}
                        try:
                            action_row["output"] = _perform_action(page, action)
                            action_row["status"] = "ok"
                        except Exception as exc:
                            action_row.update(
                                {
                                    "status": "error",
                                    "error": f"{type(exc).__name__}: {exc}",
                                }
                            )
                            row["action_status"] = "error"
                        row["actions"].append(action_row)
                        if action_row["status"] != "ok":
                            break
                    if row["action_status"] == "ok":
                        try:
                            producer = _read_observation_probe(page, producer_probe)
                            row["producer_fingerprint"] = json.dumps(
                                producer,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                            row["producer_observed"] = True
                        except Exception as exc:
                            row["producer_error"] = f"{type(exc).__name__}: {exc}"
                        try:
                            consumer = _read_observation_probe(page, consumer_probe)
                            row["consumer_fingerprint"] = json.dumps(
                                consumer,
                                ensure_ascii=False,
                                sort_keys=True,
                                separators=(",", ":"),
                            )
                            row["consumer_observed"] = True
                        except Exception as exc:
                            row["consumer_error"] = f"{type(exc).__name__}: {exc}"
                    row["evidence_ref"] = (
                        str((output_dir / f"{label}.json").resolve())
                        + f"#case={case['id']}"
                    )
                    page.screenshot(
                        path=str(output_dir / f"{label}__{case['id']}.png"),
                        full_page=True,
                    )
                    observations.append(row)
            finally:
                context.close()
        finally:
            browser.close()
    status = (
        "ok"
        if observations
        and all(
            row["action_status"] == "ok"
            and row["producer_observed"]
            and row["consumer_observed"]
            for row in observations
        )
        and not remote
        and not console_errors
        and not page_errors
        else "error"
    )
    result = {
        "schema_version": "webcoding-dependency-intervention-browser-v1",
        "status": status,
        "id": check_id.strip(),
        "project": str(project.resolve()),
        "producer_probe": producer_probe,
        "consumer_probe": consumer_probe,
        "observations": observations,
        "remote_requests": sorted(set(remote)),
        "console_errors": console_errors,
        "page_errors": page_errors,
    }
    (output_dir / f"{label}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


__all__ = [
    "dom_ax_state_records",
    "observe_project",
    "observe_url",
    "run_dependency_intervention_probe",
    "serve_project",
    "verify_layouts",
    "verify_project",
    "verify_source_gap",
]
