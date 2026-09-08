"""Attach crawled examples or explicitly labelled runtime fragments to live cards."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from instruction_augmentation.production_browser import _launch_browser, _new_page


REGIONS = ".code-box, [data-demo], [data-example], section, article, form, [role=dialog]"


def public_example_sources(locator, page_url):
    """Fetch only explicit demo-local GitHub source links, not repository bundles."""
    sources = []
    for href in locator.locator('a[href]').evaluate_all("els=>els.map(el=>el.href)"):
        parsed = urlsplit(urljoin(page_url, href))
        parts = parsed.path.strip('/').split('/')
        if (parsed.scheme != 'https' or parsed.hostname != 'github.com' or len(parts) < 5
                or parts[2] not in {'edit', 'blob'} or parts[3] not in {'master', 'main'}):
            continue
        language = Path(parts[-1]).suffix.lstrip('.')
        if language not in {'tsx', 'jsx', 'ts', 'js', 'html', 'css', 'vue'}:
            continue
        url = 'https://raw.githubusercontent.com/' + '/'.join(parts[:2] + parts[3:])
        if any(row['source_url'] == url for row in sources):
            continue
        with httpx.Client(trust_env=False, verify=True, timeout=10,
                          proxy=os.environ.get('WEBCODING_BROWSER_PROXY')) as http:
            with http.stream('GET', url) as response:
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 300000:
                        raise ValueError('public example exceeds 300000 bytes')
        sources.append({'content':data.decode('utf-8'), 'language':language,
                        'source_url':url, 'discovery_url':href, 'kind':'public_repository_file'})
        if len(sources) == 2:
            break
    return sources


def _element_selector(element):
    parts = []
    for node in [element, *element.parents]:
        if not getattr(node, "name", None) or node.name == "[document]":
            break
        if node.get("id"):
            parts.insert(0, f'[id={json.dumps(node["id"])}]')
            break
        position = len(node.find_previous_siblings(node.name)) + 1
        parts.insert(0, f"{node.name}:nth-of-type({position})")
    return " > ".join(parts)


def card_regions(card, observation):
    """Locate ownership by DOM containment in the cited action state, never by title."""
    steps = {f"{p['id']}__step_{i}": step for p in observation.get("exploration_paths", [])
             for i, step in enumerate(p.get("steps", []), 1)}
    regions = {}
    for ref in card.get("observation_evidence", []):
        step = steps.get(ref["state_id"], {})
        selector = step.get("action", {}).get("selector")
        html = step.get("state", {}).get("html", "")
        if not selector or not html or step.get("status") != "ok":
            continue
        soup = BeautifulSoup(html, "html.parser")
        base = soup.find("base", href=True)
        document_base_url = urljoin(observation.get("entry_url", ""), base["href"] if base else "")
        try:
            matches = soup.select(selector)
        except Exception:
            continue
        if len(matches) != 1:
            continue
        target = matches[0]
        ancestors = [target, *target.parents]
        # An explicit demo container is stronger than a generic inner section.
        owner = next((el for el in ancestors if getattr(el, "attrs", None)
                      and ("code-box" in el.get("class", []) or el.has_attr("data-demo")
                           or el.has_attr("data-example"))), None)
        if owner is None:
            owner = next((el for el in ancestors if getattr(el, "name", None) in
                          {"section", "article", "form", "nav", "table", "details", "dialog"}
                          or (getattr(el, "attrs", None) or {}).get("role") == "dialog"),
                         target.parent if target.parent.name not in {"body", "html", "[document]"} else target)
        region_selector = _element_selector(owner)
        content = str(owner)
        key = region_selector or sha256(content.encode()).hexdigest()
        regions.setdefault(key, {"region_selector": region_selector, "trigger_selector": selector,
                                  "state_id": ref["state_id"], "runtime_html": content,
                                  "root_tag": owner.name,
                                  "document_base_url": document_base_url,
                                  "region_scope": "structural_ancestor_candidate"})
    return list(regions.values())


COLLECT = r"""(root, includeRuntime) => {
  const examples = Array.from(root.querySelectorAll('pre')).map(pre => {
    const node = pre.querySelector('code') || pre;
    const cls = (node.className || '') + ' ' + (pre.className || '');
    const match = cls.match(/(?:language|lang)-([\w+-]+)/);
    return {content:node.innerText || node.textContent, language:match ? match[1] : 'text'};
  }).filter(row => row.content.trim());
  if (!includeRuntime) return {examples, css:''};
  const styles=[], inaccessible=[], css_sources=[];
  const ancestors=[]; for(let el=root.parentElement; el; el=el.parentElement) ancestors.push(el);
  let scanned=0, limited=false, chars=0;
  function visit(rules, parents=[], url='') {
    for (const rule of rules) {
      if (++scanned>15000 || styles.length>=500 || chars>300000) {limited=true; return;}
      if (rule.selectorText) {
        let matches=false;
        try {matches=root.matches(rule.selectorText) || !!root.querySelector(rule.selectorText)
            || ancestors.some(el=>el.matches(rule.selectorText));} catch (_) {}
        if (matches) {
          let text=rule.cssText;
          for (const header of [...parents].reverse()) text=header+'{'+text+'}';
          chars+=text.length; styles.push(text); css_sources.push({url, selector:rule.selectorText});
        }
      } else if (rule.cssRules) {
        visit(rule.cssRules, [...parents,rule.cssText.split('{')[0]], url);
      }
    }
  }
  for (const sheet of document.styleSheets) {
    try {visit(sheet.cssRules, [], sheet.href || document.URL);} catch (_) {inaccessible.push(sheet.href || 'inline');}
  }
  const nodes=[root,...root.querySelectorAll('*')];
  const js=[];
  for (const [i,el] of nodes.slice(0,500).entries()) {
    for(const attr of el.attributes) if(attr.name.startsWith('on') && attr.value.trim())
      js.push({content:attr.value, kind:'inline_event_attribute', event:attr.name, node_index:i});
    if(el.tagName==='SCRIPT' && !el.src && ['','text/javascript','application/javascript','module'].includes(el.type))
      js.push({content:el.textContent, kind:'region_inline_script', node_index:i});
  }
  return {examples, css:styles.join('\n'), css_limited:limited, css_sources,
          js, nodes_limited:nodes.length>500, inaccessible_stylesheets:inaccessible,
          document_base_url:document.baseURI,
          ancestor_context:ancestors.map(el=>({tag:el.tagName,id:el.id,class:el.className})),
          page_script_urls:Array.from(document.scripts).filter(s=>s.src).map(s=>s.src),
          page_stylesheet_urls:Array.from(document.querySelectorAll('link[rel=stylesheet]')).map(x=>x.href)};
}"""


def collect_listener_sources(cdp, selector, script_urls):
    """Read registered handlers, never execute them; ancestor delegation is only a dependency."""
    result = {"js": [], "shared_listeners": [], "warnings": []}
    group = "component_sources"
    expression = f"document.querySelector({json.dumps(selector)})"
    try:
        for shared, expr, depth in [(False, expression, 4), (True, "document", 1),
                                    (True, "window", 1), (True, expression + "?.parentElement", 1)]:
            obj = cdp.send("Runtime.evaluate", {"expression": expr, "objectGroup": group})["result"]
            if not obj.get("objectId"):
                continue
            listeners = cdp.send("DOMDebugger.getEventListeners", {
                "objectId": obj["objectId"], "depth": depth, "pierce": False})["listeners"]
            if len(listeners) > 40:
                result["warnings"].append("listener_count_limit")
            for listener in listeners[:40]:
                info = {"event": listener["type"], "script_url": script_urls.get(listener["scriptId"], ""),
                        "script_line": listener["lineNumber"] + 1,
                        "script_column": listener["columnNumber"] + 1,
                        "backend_node_id": listener.get("backendNodeId")}
                if shared:
                    result["shared_listeners"].append(info)
                    continue
                handler = listener.get("originalHandler") or listener.get("handler") or {}
                if not handler.get("objectId"):
                    result["warnings"].append("listener_source_unavailable")
                    continue
                value = cdp.send("Runtime.callFunctionOn", {"objectId": handler["objectId"],
                    "functionDeclaration": "function(){return Function.prototype.toString.call(this)}",
                    "returnByValue": True})["result"].get("value", "")
                if not value or "[native code]" in value or len(value) > 20000:
                    result["warnings"].append("native_or_oversized_listener_omitted")
                    continue
                result["js"].append({"content": value, "kind": "registered_event_listener",
                                     "closure_dependencies": "unresolved", **info})
    except Exception as exc:
        result["warnings"].append(f"listener_inspection_error: {type(exc).__name__}: {exc}")
    finally:
        cdp.send("Runtime.releaseObjectGroup", {"objectGroup": group})
    return result


def collect_direct_global_references(cdp, scripts):
    """Resolve simple inline calls only, without running a handler or invoking a getter.

    A global binding is a reference candidate: event scope shadowing and closures
    remain unresolved. Arbitrary JS expressions are deliberately not evaluated.
    """
    names = set()
    for script in scripts:
        if script["kind"] != "inline_event_attribute":
            continue
        match = re.fullmatch(r"\s*(?:return\s+)?([A-Za-z_$][\w$]*)\s*\([^;]*\)\s*;?\s*", script["content"])
        if match:
            names.add(match.group(1))
    rows = []
    try:
        for name in sorted(names)[:8]:
            obj = cdp.send("Runtime.evaluate", {"expression":
                f"Object.getOwnPropertyDescriptor(globalThis, {json.dumps(name)})?.value",
                "objectGroup":"component_direct_refs"})["result"]
            if obj.get("type") != "function" or not obj.get("objectId"):
                continue
            content = cdp.send("Runtime.callFunctionOn", {"objectId":obj["objectId"],
                "functionDeclaration":"function(){return Function.prototype.toString.call(this)}",
                "returnByValue":True})["result"].get("value", "")
            if content and "[native code]" not in content and len(content) <= 20000:
                rows.append({"kind":"referenced_global_function", "content":content,
                    "function_name":name, "attribution":"direct_inline_call_global_binding_candidate",
                    "closure_dependencies":"unresolved"})
    finally:
        cdp.send("Runtime.releaseObjectGroup", {"objectGroup":"component_direct_refs"})
    return rows


def _write_slice(directory, content, *, kind, language, url, region, index):
    digest = sha256(content.encode()).hexdigest()
    origin_key = sha256(f"{url}\n{region['region_selector']}".encode()).hexdigest()[:12]
    suffix = language if language in {"tsx", "jsx", "ts", "js", "html", "css", "vue"} else "txt"
    path = directory / f"{kind}_{digest[:12]}.{suffix}"
    path.write_text(content, encoding="utf-8")
    return {"slice_id": f"{origin_key}__{directory.name}__{index}", "path": str(path.resolve()),
            "start_line": 1, "end_line": len(content.splitlines()), "language": language,
            "sha256": digest, "content": content, "source_kind": kind,
            "source_url": url, "region_selector": region["region_selector"],
            "document_base_url": region.get("document_base_url", url),
            "evidence_state_id": region["state_id"], "locator_method": "cited_action_dom_ancestor",
            "intended_use": "implementation_reference", "generated": False,
            "dependency_closure": "partial",
            "standalone_verified": False}


def capture_component_sources(extraction, observation, output_dir: Path, *, max_regions=4,
                              include_runtime_fragments=True):
    if extraction.get("source_url") != observation.get("entry_url"):
        raise ValueError("source URL differs from browser evidence")
    if not 1 <= max_regions <= 8:
        raise ValueError("source region limit must be 1-8")
    output_dir.mkdir(parents=True, exist_ok=False)
    result = deepcopy(extraction)
    if not result["capabilities"]:
        (output_dir/"capture_summary.json").write_text(json.dumps({"region_count":0, "cards_with_sources":0}))
        return result
    url = extraction["source_url"]
    remote, errors, page_errors = [], [], []
    cache = {}
    with sync_playwright() as pw:
        browser = _launch_browser(pw, proxy=os.environ.get("WEBCODING_BROWSER_PROXY"))
        context, page = _new_page(browser, viewport={"width":1440,"height":1000},
                                  remote_requests=remote, console_errors=errors, page_errors=page_errors,
                                  network_mode="online_readonly", entry_url=url)
        cdp = context.new_cdp_session(page)
        script_urls = {}
        cdp.on("Debugger.scriptParsed", lambda event: script_urls.update({event["scriptId"]: event.get("url", "")}))
        cdp.send("Debugger.enable")
        try:
            reload_error = None
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1000)
            except Exception as exc:
                reload_error = f"{type(exc).__name__}: {exc}"
            for card in result["capabilities"]:
                for key in ("behavior_validation_status", "visual_evidence_status", "browser_check_status"):
                    card.pop(key, None)
                card["source_slices"] = []
                card["component_artifacts"] = []
                for region in card_regions(card, observation):
                    selector = region["region_selector"]
                    cache_key = selector or sha256(region["runtime_html"].encode()).hexdigest()
                    if cache_key not in cache:
                        if len(cache) >= max_regions:
                            card.setdefault("source_capture_warnings", []).append("region_limit")
                            continue
                        directory = output_dir / f"region_{len(cache)+1}"
                        directory.mkdir()
                        metadata = {"status":"runtime_dom_only", "source_url":url, **region,
                                    "examples":[], "css":"", "js":[], "shared_listeners":[]}
                        if selector:
                            try:
                                if reload_error:
                                    raise RuntimeError(reload_error)
                                locator = page.locator(selector)
                                locator.first.wait_for(state="attached", timeout=15000)
                                if locator.count() != 1:
                                    raise ValueError("region missing or ambiguous on reload")
                                if locator.evaluate("el=>el.tagName.toLowerCase()") != region["root_tag"]:
                                    raise ValueError("region tag changed on reload")
                                locator.scroll_into_view_if_needed(timeout=5000)
                                locator.wait_for(state="visible", timeout=15000)
                                metadata.update(locator.evaluate(COLLECT, include_runtime_fragments))
                                if include_runtime_fragments:
                                    listener_data = collect_listener_sources(cdp, selector, script_urls)
                                    metadata["js"].extend(listener_data.pop("js"))
                                    metadata.update(listener_data)
                                    metadata["js"].extend(collect_direct_global_references(cdp, metadata["js"]))
                                if not metadata["examples"]:
                                    try:
                                        metadata["examples"] = public_example_sources(locator, page.url)
                                    except Exception as exc:
                                        metadata.setdefault("warnings", []).append(f"public_source: {exc}")
                                if not metadata["examples"]:
                                    # Site adapter: only the code-expander actually present in this demo.
                                    toggle = locator.locator(".code-expand-icon")
                                    if toggle.count() == 1:
                                        toggle.click(timeout=5000)
                                        locator.locator("pre").first.wait_for(state="visible", timeout=15000)
                                        metadata["examples"] = locator.evaluate(COLLECT, False)["examples"]
                                locator.screenshot(path=str(directory/"region.png"), timeout=15000)
                                metadata["status"] = "page_examples" if metadata["examples"] else "runtime_fragments"
                            except Exception as exc:
                                metadata["capture_error"] = f"{type(exc).__name__}: {exc}"
                        examples = metadata.pop("examples")
                        slices = []
                        reload_region = {**region, "state_id": "source_reload"}
                        for example in examples[:4]:
                            if len(example["content"]) > 300000:
                                metadata.setdefault("warnings", []).append("example_over_size_limit")
                                continue
                            row = _write_slice(directory, example["content"], kind=example.get("kind", "page_example"),
                                language=example["language"], url=example.get("source_url", page.url),
                                region=reload_region, index=len(slices))
                            if example.get("discovery_url"):
                                row["discovery_url"] = example["discovery_url"]
                            slices.append(row)
                        runtime_html = metadata.pop("runtime_html")
                        css = metadata.pop("css")
                        runtime = []
                        if include_runtime_fragments:
                            if css:
                                runtime.append(_write_slice(directory, css, kind="runtime_matched_css", language="css",
                                    url=page.url, region=reload_region, index=11))
                            seen_js = set()
                            for js in metadata.pop("js"):
                                content = js.pop("content")
                                if not content.strip() or content in seen_js or len(content) > 20000:
                                    continue
                                seen_js.add(content)
                                row = _write_slice(directory, content, kind=js.pop("kind"), language="js",
                                    url=page.url, region=reload_region, index=12+len(runtime))
                                row["binding"] = js
                                runtime.append(row)
                        else:
                            metadata.pop("js", None)
                        metadata["status"] = ("page_examples" if slices else
                            "partial_reference" if include_runtime_fragments else "source_unavailable")
                        metadata.update({"standalone_verified":False, "scripts_scope":"page_level_unattributed",
                            "css_scope":"current_reload_state_only_not_dependency_closed",
                            "intended_use":"implementation_reference", "dependency_closure":"partial",
                            "browser_guard":"write_requests_and_form_submission_blocked",
                            "missing_or_unresolved":["module_imports_and_function_closures", "dynamic_states",
                                "shadow_dom_and_iframe_contents", "css_pseudo_states_keyframes_and_font_rules"],
                            "example_count":len(slices), "artifact_paths":[s["path"] for s in slices+runtime]})
                        (directory/"metadata.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
                        cache[cache_key] = (slices + runtime, metadata, str(directory.resolve()))
                    slices, metadata, directory = cache[cache_key]
                    card["source_slices"].extend({**s, "related_observation_state_id":region["state_id"]} for s in slices)
                    if include_runtime_fragments:
                        dom = _write_slice(Path(directory), region["runtime_html"], kind="runtime_dom",
                            language="html", url=url, region=region, index=f"dom_{region['state_id']}")
                        card["source_slices"].append(dom)
                        if dom["path"] not in metadata["artifact_paths"]:
                            metadata["artifact_paths"].append(dom["path"])
                            (Path(directory)/"metadata.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2))
                    card["component_artifacts"].append({"directory":directory, "region_selector":selector,
                        "status":metadata["status"], "example_count":metadata["example_count"],
                        "metadata_path":str(Path(directory)/"metadata.json")})
                card["source_reference_policy"] = {"intended_use":"implementation_reference",
                    "generated":False, "dependency_closure":"partial", "standalone_verified":False}
                card["source_capture_status"] = "captured" if card["source_slices"] else "unmapped"
        finally:
            context.close()
            browser.close()
    (output_dir/"capture_summary.json").write_text(json.dumps({"region_count":len(cache),
        "cards_with_sources":sum(bool(c["source_slices"]) for c in result["capabilities"]),
        "console_errors":errors, "page_errors":page_errors},ensure_ascii=False,indent=2))
    return result


def main():
    """Bounded, opt-in source enrichment of one already-mined URL; no LLM calls."""
    import argparse
    import signal
    import sys
    from scripts.run_live_url_audit_case import supervise

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extraction", type=Path, required=True)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-regions", type=int, default=2, choices=range(1, 9))
    parser.add_argument("--seconds", type=int, default=180)
    parser.add_argument("--browser-proxy")
    parser.add_argument("--include-runtime-fragments", action="store_true", default=True,
                        help="Reference mode default: retain DOM/CSS and attributable JS")
    parser.add_argument("--examples-only", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 600:
        parser.error("deadline must be 1-600 seconds")
    if args.worker:
        result = capture_component_sources(json.loads(args.extraction.read_text()),
            json.loads(args.observation.read_text()), args.output / "components",
            max_regions=args.max_regions, include_runtime_fragments=not args.examples_only)
        (args.output / "extraction_with_sources.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        from scripts.mine_live_url_capability_pool import compact_live_card, write_jsonl
        write_jsonl(args.output / "capability_pool.jsonl", [compact_live_card(c) for c in result["capabilities"]])
        print(json.dumps({"cards": len(result["capabilities"]), "cards_with_sources":
            sum(bool(c["source_slices"]) for c in result["capabilities"])}), flush=True)
        return 0
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    for name in ["ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "all_proxy", "https_proxy", "http_proxy"]:
        env.pop(name, None)
    if args.browser_proxy:
        env["WEBCODING_BROWSER_PROXY"] = args.browser_proxy
    env.update(PYTHONPATH=str(root), PYTHONUNBUFFERED="1")
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    for sig in [signal.SIGHUP, signal.SIGTERM, signal.SIGINT]:
        signal.signal(sig, interrupted)
    command = [sys.executable, "-m", "instruction_augmentation.live_component_sources",
        "--worker", "--extraction", str(args.extraction.resolve()), "--observation",
        str(args.observation.resolve()), "--output", str(args.output.resolve()),
        "--max-regions", str(args.max_regions)]
    if args.examples_only:
        command.append("--examples-only")
    result = supervise(command, cwd=root, run_dir=args.output.resolve(), seconds=args.seconds, env=env)
    print(json.dumps(result), flush=True)
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
