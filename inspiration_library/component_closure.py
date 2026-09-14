#!/usr/bin/env python3
"""Extract a browser-observed HTML/CSS/JS dependency closure for one component.

This produces usable implementation references, with separately reported replay
and dependency limits. It keeps the real DOM context chain, selects CSS
rules through the page's CSSOM, records event listeners before page scripts run,
and follows imports for JavaScript resources that Playwright observed loading.

Example:

    python inspiration_library/component_closure.py \
      https://example.com --selector '[data-testid="checkout-card"]' \
      --output-dir runs/checkout-card

The output directory contains ``index.html``, ``component.css``, a ``scripts/``
directory and ``manifest.json``.  External images/fonts are reported in the
manifest but are not downloaded by default.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from playwright.sync_api import Browser, Page, Response, sync_playwright
from tree_sitter import Language, Parser
import tree_sitter_javascript


EVENT_RECORDER = r"""
(() => {
  if (window.__componentClosureRecorder) return;
  const records = [];
  const shadowRoots = new WeakMap();
  const attachShadow = Element.prototype.attachShadow;
  Element.prototype.attachShadow = function(options) {
    const root = attachShadow.call(this, options);
    shadowRoots.set(this, root);
    return root;
  };
  const shadowFor = el => el.shadowRoot || shadowRoots.get(el);
  const elements = (root = document) => {
    const result = [...root.querySelectorAll('*')];
    for (const el of [...result]) {
      const shadow = shadowFor(el);
      if (shadow) result.push(...elements(shadow));
    }
    return result;
  };
  const serialize = node => {
    const clone = node.cloneNode(false);
    if (node.nodeType !== Node.ELEMENT_NODE) return clone;
    for (const attr of ['src', 'poster', 'data']) {
      const value=node.getAttribute(attr);
      if (value && !/^(?:data:|blob:|#)/.test(value)) {
        try { clone.setAttribute(attr, new URL(value, document.baseURI).href); } catch (_) {}
      }
    }
    for (const child of node.childNodes) clone.append(serialize(child));
    if (node instanceof HTMLInputElement) {
      clone.setAttribute('value', node.value);
      clone.toggleAttribute('checked', node.checked);
    }
    if (node instanceof HTMLTextAreaElement) clone.textContent = node.value;
    if (node instanceof HTMLOptionElement) clone.toggleAttribute('selected', node.selected);
    const shadow = shadowFor(node);
    if (shadow) {
      const template = document.createElement('template');
      template.setAttribute('shadowrootmode', shadow.mode);
      for (const child of shadow.childNodes) template.content.append(serialize(child));
      for (const sheet of shadow.adoptedStyleSheets || []) {
        const style = document.createElement('style');
        style.textContent = [...sheet.cssRules].map(rule => rule.cssText).join('\n');
        template.content.append(style);
      }
      clone.prepend(template);
    }
    return clone;
  };
  const original = EventTarget.prototype.addEventListener;
  EventTarget.prototype.addEventListener = function(type, listener, options) {
    try {
      if (records.length < 10000) records.push({
        target: this,
        type: String(type),
        source: typeof listener === 'function'
          ? Function.prototype.toString.call(listener)
          : String(listener)
      });
    } catch (_) {}
    return original.call(this, type, listener, options);
  };
  window.__componentClosureRecorder = {records, elements, shadowFor, serialize};
})();
"""


COLLECT_PAGE_DATA = r"""
({selector, index, capturedSheets = {}}) => {
  const recorder = window.__componentClosureRecorder;
  const all = [...document.querySelectorAll(selector)];
  for (const el of recorder?.elements() || []) {
    const shadow = recorder.shadowFor(el);
    if (shadow) for (const match of shadow.querySelectorAll(selector)) {
      if (!all.includes(match)) all.push(match);
    }
  }
  const root = all[index];
  if (!root) {
    throw new Error(`selector matched ${all.length} elements; index ${index} is unavailable`);
  }

  const descendants = [root, ...(recorder ? recorder.elements(root) : root.querySelectorAll('*'))];
  const associated = [];
  for (const node of [...descendants]) {
    for (const attr of ['aria-controls', 'aria-owns']) {
      for (const id of (node.getAttribute(attr) || '').split(/\s+/).filter(Boolean)) {
        const target = document.getElementById(id);
        if (target && !descendants.includes(target)) {
          associated.push(target);
          descendants.push(target, ...target.querySelectorAll('*'));
        }
      }
    }
  }
  const ancestors = [];
  let cursor = root.parentElement;
  while (cursor) {
    ancestors.push(cursor);
    cursor = cursor.parentElement;
  }

  const tokens = new Set();
  const addToken = value => {
    if (value && String(value).trim()) tokens.add(String(value).trim().toLowerCase());
  };
  for (const node of descendants) {
    addToken(node.id);
    for (const cls of node.classList || []) addToken(cls);
    for (const attr of ['data-testid', 'data-component', 'aria-label', 'role', 'name']) {
      addToken(node.getAttribute(attr));
    }
  }
  const tokenList = [...tokens].filter(t => t.length >= 2).slice(0, 80);
  const tokenPattern = tokenList.length
    ? new RegExp(`(?:^|[^a-z0-9_-])(?:${tokenList.map(t =>
        t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})(?:$|[^a-z0-9_-])`, 'i')
    : null;

  const safeMatches = (node, selectorText) => {
    try { return node.matches(selectorText); } catch (_) { return false; }
  };
  const selectorMatchesComponent = selectorText => {
    if (!selectorText) return false;
    const parts = selectorText.split(',').map(x => x.trim()).filter(Boolean);
    for (const part of parts) {
      if (descendants.some(node => safeMatches(node, part))) return true;
      // Include state/pseudo-element rules that are not active at extraction time.
      const base = part
        .replace(/::[a-z-]+(?:\([^)]*\))?/gi, '')
        .replace(/:(?:hover|active|focus|focus-visible|focus-within|visited|target|checked|disabled|enabled|open|placeholder-shown)(?![-\w])/gi, '');
      if (base && descendants.some(node => safeMatches(node, base))) return true;
      if (tokenPattern && tokenPattern.test(part)) return true;
    }
    return false;
  };

  const usedAnimations = new Set();
  const usedFonts = new Set();
  const neededVars = new Set();
  for (const node of descendants) {
    const style = getComputedStyle(node);
    for (const property of ['animation-name', 'font-family']) {
      for (const value of String(style.getPropertyValue(property) || '').split(',')) {
        const cleaned = value.trim().replace(/^['"]|['"]$/g, '');
        if (property === 'animation-name' && cleaned && cleaned !== 'none') usedAnimations.add(cleaned);
        if (property === 'font-family' && cleaned) usedFonts.add(cleaned.toLowerCase());
      }
    }
    const inline = node.getAttribute('style') || '';
    for (const match of inline.matchAll(/var\(\s*(--[\w-]+)/g)) neededVars.add(match[1]);
  }

  const eventRecords = (window.__componentClosureRecorder?.records || []).map(record => {
    let related = false;
    try {
      const target = record.target;
      related = target === root || target === document || target === window ||
        (target instanceof Node && (root.contains(target) || target.contains(root)));
    } catch (_) {}
    const source = String(record.source || '');
    if (tokenPattern && tokenPattern.test(source)) related = true;
    return related ? {type: record.type, source} : null;
  }).filter(Boolean);

  const selectorMatchesAncestors = selectorText => {
    if (!selectorText) return false;
    return selectorText.split(',').some(part => {
      const cleaned = part.trim();
      return ancestors.some(node => safeMatches(node, cleaned));
    });
  };

  const collectVariableReferences = rules => {
    for (const rule of [...rules]) {
      if (rule.type === 1 && selectorMatchesComponent(rule.selectorText)) {
        for (const match of String(rule.cssText || '').matchAll(/var\(\s*(--[\w-]+)/g)) {
          neededVars.add(match[1]);
        }
      } else if ([4, 12, 17, 18].includes(rule.type)) {
        collectVariableReferences(rule.cssRules || []);
      }
    }
  };

  const serializeNested = (rules, parentText = '') => {
    const output = [];
    for (const rule of [...rules]) {
      // STYLE_RULE
      if (rule.type === 1) {
        const text = String(rule.cssText || '');
        if (selectorMatchesComponent(rule.selectorText) ||
            selectorMatchesAncestors(rule.selectorText) ||
            [...neededVars].some(name => text.includes(name))) {
          output.push({text, kind: 'style', selector: String(rule.selectorText || ''), parent: parentText});
          for (const match of text.matchAll(/var\(\s*(--[\w-]+)/g)) neededVars.add(match[1]);
        }
        continue;
      }
      // KEYFRAMES_RULE, including vendor-prefixed variants.
      if (rule.type === 7 || rule.type ===  keyframesRuleType()) {
        const name = String(rule.name || '').toLowerCase();
        if (usedAnimations.has(name) || usedAnimations.has(String(rule.name || ''))) {
          output.push({text: String(rule.cssText || ''), kind: 'keyframes', selector: name, parent: parentText});
        }
        continue;
      }
      // FONT_FACE_RULE.
      if (rule.type === 5) {
        const family = String(rule.style?.getPropertyValue('font-family') || '').replace(/["']/g, '').trim().toLowerCase();
        if (family && [...usedFonts].some(font => font.includes(family) || family.includes(font))) {
          output.push({text: String(rule.cssText || ''), kind: 'font-face', selector: family, parent: parentText});
        }
        continue;
      }
      // MEDIA_RULE, SUPPORTS_RULE, CONTAINER_RULE and LAYER_RULE.
      if ([4, 12, 17, 18].includes(rule.type)) {
        const condition = String(rule.cssText).split('{', 1)[0].trim().replace(/^@/, '');
        const nested = serializeNested(rule.cssRules || [], condition);
        if (nested.length) output.push({group: condition, kind: 'group', children: nested});
        continue;
      }
      // @import cannot be made minimal without resolving another sheet here.
      if (rule.type === 3) {
        output.push({text: String(rule.cssText || ''), kind: 'unresolved-import'});
      }
    }
    return output;
  };

  const stylesheetData = [];
  const inaccessibleSheets = [];
  const collectSheets = () => {
    for (const sheet of [...document.styleSheets]) {
      try {
        collectVariableReferences(sheet.cssRules || []);
        const rules = serializeNested(sheet.cssRules || []);
        if (rules.length) stylesheetData.push({href: sheet.href || null, rules});
      } catch (error) {
        if (capturedSheets[sheet.href]) {
          const readable = new CSSStyleSheet();
          readable.replaceSync(capturedSheets[sheet.href]);
          collectVariableReferences(readable.cssRules);
          stylesheetData.push({href: sheet.href, rules: serializeNested(readable.cssRules)});
        } else inaccessibleSheets.push({href: sheet.href || null, error: String(error)});
      }
    }
  };
  collectSheets();

  const replayNormalizations = [];
  const cloneWithoutRuntimeScripts = node => {
    const clone = recorder ? recorder.serialize(node) : node.cloneNode(true);
    // The real bootstrap script recreates these widget-owned nodes. Keeping
    // them in an already-initialized DOM would render each arrow twice.
    const originals = [node, ...node.querySelectorAll('*')];
    const copies = [clone, ...clone.querySelectorAll('*')];
    for (const original of originals) {
      const instance = window.jQuery?.data?.(original, 'ui-accordion');
      if (!instance?.headers) continue;
      let removed = 0;
      for (const header of instance.headers) {
        const copy = copies[originals.indexOf(header)];
        if (!copy) continue;
        copy.querySelectorAll(':scope > .ui-accordion-header-icon').forEach(icon => { icon.remove(); removed++; });
      }
      for (const [key, elements] of Object.entries(instance.classesElementLookup || {})) {
        const classes = `${key} ${instance.options?.classes?.[key] || ''}`.split(/\s+/).filter(Boolean);
        for (const element of Array.from(elements)) {
          const copy = copies[originals.indexOf(element)];
          if (copy) copy.classList.remove(...classes);
        }
      }
      if (removed) replayNormalizations.push({kind:'jquery_ui_accordion_generated_state', removed});
    }
    clone.querySelectorAll('script, link[rel="stylesheet"]').forEach(item => item.remove());
    const assetAttrs = [
      ['img', 'src'], ['source', 'src'], ['video', 'src'], ['audio', 'src'],
      ['video', 'poster'], ['iframe', 'src'], ['object', 'data'], ['form', 'action']
    ];
    for (const [tag, attr] of assetAttrs) {
      [clone, ...clone.querySelectorAll('*')].filter(item => item.matches(`${tag}[${attr}]`)).forEach(item => {
        const value = item.getAttribute(attr);
        if (value) item.setAttribute(attr, new URL(value, document.baseURI).href);
      });
    }
    const rewriteInlineStyle = item => {
      const value = item.getAttribute('style') || '';
      item.setAttribute('style', value.replace(/url\(\s*(['"]?)(.*?)\1\s*\)/gi, (full, quote, raw) => {
        if (!raw || /^(?:data|blob|https?):|^#/.test(raw)) return full;
        try { return `url('${new URL(raw, document.baseURI).href}')`; } catch (_) { return full; }
      }));
    };
    if (clone.matches && clone.matches('[style]')) rewriteInlineStyle(clone);
    clone.querySelectorAll('[style]').forEach(rewriteInlineStyle);
    clone.querySelectorAll('[srcset]').forEach(item => {
      const value = item.getAttribute('srcset') || '';
      item.setAttribute('srcset', value.split(',').map(part => {
        const bits = part.trim().split(/\s+/);
        if (bits[0]) bits[0] = new URL(bits[0], document.baseURI).href;
        return bits.join(' ');
      }).join(', '));
    });
    return clone;
  };

  let component = cloneWithoutRuntimeScripts(root);
  let parent = root.parentElement;
  while (parent && parent !== document.body && parent !== document.documentElement) {
    const shell = parent.cloneNode(false);
    shell.append(component);
    component = shell;
    parent = parent.parentElement;
  }
  const body = document.body ? document.body.cloneNode(false) : document.createElement('body');
  if (root === document.body) body.append(...component.childNodes);
  else body.append(component);
  for (const node of associated) body.append(cloneWithoutRuntimeScripts(node));
  const html = document.documentElement.cloneNode(false);
  html.setAttribute('data-component-closure', 'true');
  const head = document.createElement('head');
  const title = document.createElement('title');
  title.textContent = document.title || 'Extracted component';
  head.append(title);
  html.append(head, body);

  const scripts = [...document.scripts].map((script, order) => ({
    order,
    src: script.src || null,
    inline: script.src ? '' : String(script.textContent || ''),
    type: script.getAttribute('type') || '',
    attrs: [...script.attributes].reduce((acc, attr) => {
      if (attr.name !== 'src') acc[attr.name] = attr.value;
      return acc;
    }, {})
  }));
  const inlineHandlers = [...descendants].flatMap(node =>
    [...node.attributes].filter(attr => /^on/i.test(attr.name)).map(attr => ({name: attr.name, value: attr.value}))
  );
  const externalAssets = new Set();
  for (const node of [root, ...root.querySelectorAll('*')]) {
    for (const attr of ['src', 'poster', 'data']) {
      const value = node.getAttribute(attr);
      if (value && !value.startsWith('#') && !value.startsWith('data:') && !value.startsWith('javascript:')) {
        try { externalAssets.add(new URL(value, document.baseURI).href); } catch (_) {}
      }
    }
  }
  return {
    base_url: document.baseURI,
    title: document.title,
    html: '<!doctype html>\n' + html.outerHTML,
    tokens: tokenList,
    stylesheet_data: stylesheetData,
    inaccessible_sheets: inaccessibleSheets,
    scripts,
    events: eventRecords,
    inline_handlers: inlineHandlers,
    external_assets: [...externalAssets],
    selector_count: all.length,
    replay_normalizations: replayNormalizations,
  };

  function keyframesRuleType() { return window.CSSRule?.KEYFRAMES_RULE || 7; }
}
"""


@dataclass
class CapturedResource:
    url: str
    body: bytes
    content_type: str
    status: int


def _safe_name(value: str, fallback: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return (name[:80] or fallback)


def _capture_response(response: Response, resources: dict[str, CapturedResource]) -> None:
    request = response.request
    if request.resource_type not in {"script", "stylesheet"} or response.status >= 400:
        return
    try:
        body = response.body()
    except Exception:
        return
    resources[response.url] = CapturedResource(
        url=response.url,
        body=body,
        content_type=response.headers.get("content-type", ""),
        status=response.status,
    )


def _css_text(rule: dict[str, Any]) -> str:
    if rule.get("kind") == "group":
        children = "\n".join(_css_text(child) for child in rule.get("children", []))
        return f"@{rule.get('group', '')} {{\n{children}\n}}"
    return str(rule.get("text", ""))


def _absolutize_css_urls(css: str, base_url: str) -> str:
    def replace(match: re.Match[str]) -> str:
        raw = match.group(1).strip().strip('"\'')
        if not raw or raw.startswith(("data:", "blob:", "#", "http://", "https://")):
            return match.group(0)
        return f"url('{urljoin(base_url, raw)}')"

    return re.sub(r"url\(\s*([^)]*?)\s*\)", replace, css, flags=re.I)


def _css_asset_urls(css: str, base_url: str) -> list[str]:
    urls = []
    for match in re.finditer(r"url\(\s*(['\"]?)(.*?)\1\s*\)", css, flags=re.I):
        raw = match.group(2).strip()
        if not raw or raw.startswith(("data:", "blob:", "#")):
            continue
        urls.append(urljoin(base_url, raw))
    return list(dict.fromkeys(urls))


def _identity_matches(text: str, tokens: list[str]) -> bool:
    lowered = text.lower()
    return any(re.search(rf"(?<![a-z0-9_-]){re.escape(token)}(?![a-z0-9_-])", lowered) for token in tokens)


def _import_spans(source: str) -> list[tuple[int, int, str]]:
    """Parse literal module specifiers, excluding comments and unrelated strings."""
    parser = Parser(Language(tree_sitter_javascript.language()))
    raw = source.encode("utf-8")
    stack = [parser.parse(raw).root_node]
    found = []
    while stack:
        node = stack.pop()
        value = None
        if node.type in {"import_statement", "export_statement"}:
            value = node.child_by_field_name("source")
        elif node.type == "call_expression":
            function = node.child_by_field_name("function")
            arguments = node.child_by_field_name("arguments")
            if function and function.type == "import" and arguments and arguments.named_children:
                value = arguments.named_children[0]
        if value and value.type == "string":
            found.append((value.start_byte, value.end_byte, raw[value.start_byte+1:value.end_byte-1].decode("utf-8")))
        stack.extend(node.children)
    return sorted(found)


def _extract_imports(source: str) -> list[str]:
    return list(dict.fromkeys(value for _, _, value in _import_spans(source)))


def _select_css(data: dict[str, Any], base_url: str) -> tuple[str, dict[str, Any]]:
    rules = []
    imports = []
    for sheet in data.get("stylesheet_data", []):
        sheet_base = str(sheet.get("href") or base_url)
        for rule in sheet.get("rules", []):
            if rule.get("kind") == "unresolved-import":
                imports.append(_absolutize_css_urls(str(rule.get("text", "")), sheet_base))
            else:
                rules.append(_absolutize_css_urls(_css_text(rule), sheet_base))
    css = "\n".join(rules).strip() + "\n"
    details = {
        "matched_rule_count": len(rules),
        "inaccessible_stylesheets": data.get("inaccessible_sheets", []),
        "unresolved_imports": imports,
    }
    return css, details


def _script_is_selected(script: dict[str, Any], tokens: list[str], event_sources: list[str], include_all: bool) -> tuple[bool, str]:
    if include_all:
        return True, "include_all_scripts"
    source = str(script.get("inline") or "")
    if source and _identity_matches(source, tokens):
        return True, "inline_script_references_component_identity"
    if source and any(_identity_matches(event, tokens) for event in event_sources):
        return True, "runtime_event_listener_references_component_identity"
    if script.get("src") and _identity_matches(str(script.get("src")), tokens):
        return True, "script_url_references_component_identity"
    return False, "not_referenced_by_observed_identity"


def _write_scripts(
    data: dict[str, Any],
    resources: dict[str, CapturedResource],
    output_dir: Path,
    include_all: bool,
    max_js_bytes: int,
) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    scripts_dir = output_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    tokens = list(data.get("tokens", []))
    event_sources = [str(item.get("source", "")) for item in data.get("events", [])]
    descriptors = list(data.get("scripts", []))
    if include_all:
        entry_urls = {script.get("src") for script in descriptors}
        descriptors.extend({"src": url, "inline": "", "attrs": {}, "dependency_only": True}
                           for url, resource in resources.items()
                           if url not in entry_urls and "javascript" in resource.content_type.lower())
    included: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    unresolved: list[str] = []

    for script in descriptors:
        src = script.get("src")
        source = str(script.get("inline") or "")
        if src and not source:
            resource = resources.get(str(src))
            if resource is None:
                omitted.append({"src": src, "reason": "script_body_not_captured"})
                unresolved.append(str(src))
                continue
            source = resource.body.decode("utf-8", errors="replace")
        selected, reason = _script_is_selected({**script, "inline": source}, tokens, event_sources, include_all)
        if not selected:
            omitted.append({"src": src, "reason": reason})
            continue
        if len(source.encode("utf-8")) > max_js_bytes:
            omitted.append({"src": src, "reason": "script_exceeds_max_js_bytes", "bytes": len(source.encode("utf-8"))})
            unresolved.append(str(src or f"inline:{script.get('order')}"))
            continue
        included.append({"descriptor": script, "source": source, "reason": reason,
                         "dependency_only": script.get("dependency_only", False)})

    # If a component has observed listeners but no script was selected, retain
    # the small page's scripts as a safer candidate and say so explicitly.
    if data.get("events") and not included and descriptors and not include_all:
        for script in descriptors:
            src = script.get("src")
            source = str(script.get("inline") or "")
            if src and not source and src in resources:
                source = resources[src].body.decode("utf-8", errors="replace")
            if source and len(source.encode("utf-8")) <= max_js_bytes:
                included.append({"descriptor": script, "source": source, "reason": "fallback_for_observed_runtime_listener"})
        unresolved.append("runtime_listener_source_to_script_mapping")

    # Follow relative ESM imports among resources already observed by Playwright.
    by_url = dict(resources)
    queue = [(item["descriptor"].get("src") or data["base_url"], item["source"]) for item in included]
    seen = {item["descriptor"].get("src") for item in included}
    while queue:
        parent_url, source = queue.pop(0)
        for import_ref in _extract_imports(source):
            if import_ref.startswith(("/", "./", "../")) or import_ref.startswith(("http://", "https://")):
                resolved = urljoin(str(parent_url), import_ref)
                if resolved in by_url and resolved not in seen:
                    child = by_url[resolved]
                    if len(child.body) <= max_js_bytes:
                        included.append({
                            "descriptor": {"order": 10_000 + len(included), "src": resolved, "inline": "", "type": "module", "attrs": {"type": "module"}},
                            "source": child.body.decode("utf-8", errors="replace"),
                            "reason": f"esm_import_of:{parent_url}",
                            "dependency_only": True,
                        })
                        seen.add(resolved)
                        queue.append((resolved, child.body.decode("utf-8", errors="replace")))
                    else:
                        unresolved.append(resolved)
                elif resolved not in by_url:
                    unresolved.append(resolved)
            else:
                unresolved.append(import_ref)

    local_names: dict[str, str] = {}
    for index, item in enumerate(included, start=1):
        descriptor = item["descriptor"]
        source = item["source"]
        src = descriptor.get("src")
        base = _safe_name(Path(urlparse(str(src)).path).name if src else f"inline_{index}.js", f"script_{index}.js")
        if not base.endswith(".js"):
            base += ".js"
        filename = f"{index:02d}_{hashlib.sha256(str(src or source[:200]).encode()).hexdigest()[:8]}_{base}"
        if src:
            local_names[str(src)] = f"scripts/{filename}"
        item["local_path"] = scripts_dir / filename

    for item in included:
        source = item["source"]
        base = item["descriptor"].get("src") or data["base_url"]
        raw = source.encode("utf-8")
        for start, end, original in reversed(_import_spans(source)):
            local = local_names.get(urljoin(base, original))
            if local:
                raw = raw[:start] + json.dumps("./" + Path(local).name).encode() + raw[end:]
        item["local_path"].write_bytes(raw)

    tags: list[str] = []
    for item in included:
        if item.get("dependency_only"):
            continue
        descriptor = item["descriptor"]
        attrs = dict(descriptor.get("attrs") or {})
        src = descriptor.get("src")
        attrs.pop("integrity", None)
        attrs["src"] = "./" + str(item["local_path"].relative_to(output_dir))
        rendered = " ".join(f'{key}="{_html_escape(str(value))}"' for key, value in attrs.items())
        tags.append(f"<script {rendered}></script>")
    return tags, included + omitted, unresolved


def _html_escape(value: str) -> str:
    return (value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;"))


def extract_component(
    url: str,
    selector: str,
    output_dir: str | Path,
    *,
    index: int = 0,
    wait_until: str = "networkidle",
    timeout_ms: int = 30_000,
    include_all_scripts: bool = False,
    max_js_bytes: int = 2_000_000,
    browser_proxy: str | None = None,
    browser: Browser | None = None,
    page: Page | None = None,
    captured_resources: dict[str, CapturedResource] | None = None,
) -> dict[str, Any]:
    """Extract one selector and return the written manifest.

    A caller may pass an existing Playwright ``Browser`` to reuse a controlled
    browser.  The function owns the context and page in that case.
    """
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    resources = captured_resources if captured_resources is not None else {}
    own_page = page is None
    own_browser = own_page and browser is None

    with sync_playwright() if own_browser else _null_context() as playwright:
        if own_browser:
            proxy = browser_proxy or os.environ.get("WEBCODING_BROWSER_PROXY")
            options = {"proxy": {"server": proxy}} if proxy else {}
            browser = playwright.chromium.launch(headless=True, **options)
        context = None
        if own_page:
            assert browser is not None
            context = browser.new_context()
            page = context.new_page()
            page.add_init_script(EVENT_RECORDER)
            page.on("response", lambda response: _capture_response(response, resources))
        assert page is not None
        try:
            if own_page:
                page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            sheets = {resource.url: resource.body.decode("utf-8", errors="replace")
                      for resource in resources.values() if "css" in resource.content_type.lower()}
            data = page.evaluate(COLLECT_PAGE_DATA, {"selector": selector, "index": index, "capturedSheets": sheets})
        finally:
            if context is not None:
                context.close()
            if own_browser:
                browser.close()

    css, css_details = _select_css(data, data.get("base_url") or url)
    (destination / "component.css").write_text(css, encoding="utf-8")
    script_tags, script_entries, unresolved_js = _write_scripts(
        data, resources, destination, include_all_scripts, max_js_bytes,
    )
    html = data["html"]
    html = html.replace("</head>", '  <link rel="stylesheet" href="./component.css">\n</head>', 1)
    if script_tags:
        html = html.replace("</body>", "\n" + "\n".join(script_tags) + "\n</body>", 1)
    (destination / "index.html").write_text(html, encoding="utf-8")

    included_scripts = [entry for entry in script_entries if "source" in entry]
    omitted_scripts = [entry for entry in script_entries if "source" not in entry]
    warnings = []
    if data.get("inaccessible_sheets"):
        warnings.append("one or more stylesheets were cross-origin/inaccessible to CSSOM; captured response bodies were used when available")
    if css_details["unresolved_imports"]:
        warnings.append("CSS @import rules were observed but not recursively materialized")
    if unresolved_js:
        warnings.append("some JavaScript imports or runtime-to-script mappings remain unresolved")
    if data.get("events") and not included_scripts:
        warnings.append("runtime listeners were observed but no executable script was selected")

    external_assets = list(dict.fromkeys(
        list(data.get("external_assets", [])) + _css_asset_urls(css, data.get("base_url") or url)
    ))
    manifest = {
        "schema_version": 1,
        "closure_status": "available",
        "intended_use": "implementation_reference",
        "capture_state": "loaded_page" if own_page else "current_live_state",
        "standalone_verified": False,
        "replay_normalizations": data.get("replay_normalizations", []),
        "source_url": url,
        "base_url": data.get("base_url"),
        "selector": selector,
        "selector_index": index,
        "selector_match_count": data.get("selector_count"),
        "outputs": ["index.html", "component.css"] + (["scripts/"] if included_scripts else []),
        "html": {
            "context": "body ancestor chain + selected subtree",
            "tokens": data.get("tokens", []),
            "inline_event_handlers": data.get("inline_handlers", []),
        },
        "css": css_details,
        "javascript": {
            "observed_event_listeners": data.get("events", []),
            "included": [
                {"src": item.get("descriptor", {}).get("src"), "reason": item.get("reason"), "path": str(item.get("local_path").relative_to(destination))}
                for item in included_scripts
            ],
            "omitted": omitted_scripts,
            "unresolved_imports": unresolved_js,
        },
        "external_assets": external_assets,
        "warnings": warnings,
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


class _null_context:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: Any) -> None:
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--selector", required=True, help="CSS selector identifying exactly one component instance")
    parser.add_argument("--selector-index", type=int, default=0)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--wait-until", choices=["commit", "domcontentloaded", "load", "networkidle"], default="networkidle")
    parser.add_argument("--timeout-ms", type=int, default=30_000)
    parser.add_argument("--include-all-scripts", action="store_true", help="include every loaded script; useful when bundles hide selector strings")
    parser.add_argument("--max-js-bytes", type=int, default=2_000_000)
    parser.add_argument("--browser-proxy", help="Browser-only proxy; API traffic is not routed through it")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = extract_component(
            args.url,
            args.selector,
            args.output_dir,
            index=args.selector_index,
            wait_until=args.wait_until,
            timeout_ms=args.timeout_ms,
            include_all_scripts=args.include_all_scripts,
            max_js_bytes=args.max_js_bytes,
            browser_proxy=args.browser_proxy,
        )
    except Exception as error:
        print(f"component extraction failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({
        "output_dir": str(args.output_dir),
        "closure_status": manifest["closure_status"],
        "css_rules": manifest["css"]["matched_rule_count"],
        "included_scripts": len(manifest["javascript"]["included"]),
        "warnings": manifest["warnings"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
