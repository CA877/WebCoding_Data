from inspiration_library.live_component_sources import card_regions, _write_slice
from scripts.mine_live_url_capability_pool import compact_live_card
import os
import pytest


@pytest.mark.skipif(os.environ.get("WEBCODING_PUBLIC_REFERENCE_PROBE") != "1",
                    reason="Explicit bounded physical-host probe only")
def test_public_ant_code_expansion(tmp_path):
    """Actual demo source links and a complete three-click sorter cycle."""
    import json
    from playwright.sync_api import sync_playwright
    from inspiration_library.production_browser import _launch_browser, _new_page, _snapshot
    from inspiration_library.live_component_sources import public_example_sources
    with sync_playwright() as pw:
        browser = _launch_browser(pw)
        errors = []
        context, page = _new_page(browser, viewport={"width":1440,"height":1000},
            remote_requests=[], console_errors=[], page_errors=errors,
            network_mode="online_readonly", entry_url="https://ant.design/components/table")
        rows, states, steps = [], [], []
        try:
            page.goto("https://ant.design/components/table", wait_until="domcontentloaded", timeout=30000)
            for name in ["dynamic-settings", "multiple-sorter"]:
                region = page.locator("#table-demo-" + name)
                region.wait_for(timeout=15000)
                sources = public_example_sources(region, page.url)
                assert sources and 'export default' in sources[0]['content']
                rows.append({"demo":name,"sources":sources})
            region = page.locator("#table-demo-multiple-sorter")
            region.scroll_into_view_if_needed()
            region.locator('tbody tr td:nth-child(2)').first.wait_for(state='visible', timeout=15000)
            selector = '#table-demo-multiple-sorter th.ant-table-column-has-sorters:nth-child(2)'
            def snapshot_state(index):
                shot = tmp_path / f'sort_{index}.png'
                region.screenshot(path=str(shot), timeout=10000)
                state = _snapshot(page)
                state['screenshot_path'] = str(shot.resolve())
                state['screenshot_scope'] = '#table-demo-multiple-sorter'
                names = region.locator('tbody tr td:first-child').all_text_contents()
                scores = [int(v) for v in region.locator('tbody tr td:nth-child(2)').all_text_contents()]
                states.append({'names':names,'scores':scores,'aria_sort':page.locator(selector).get_attribute('aria-sort')})
                return state
            before = snapshot_state(0)
            for i in range(1,4):
                page.locator(selector).click(timeout=5000)
                page.wait_for_timeout(200)
                steps.append({'status':'ok','action':{'action':'click','selector':selector},'state':snapshot_state(i)})
            observation = {'source_kind':'live_url','status':'ok','entry_url':page.url,'baseline':before,
                'mobile_baseline':{},'exploration_paths':[{'id':'sort_cycle','status':'ok',
                    'purpose':'Observe ascending, descending and reset on the Chinese Score column',
                    'before':before,'steps':steps,'after':steps[-1]['state']}]}
            (tmp_path/'observation.json').write_text(json.dumps(observation))
            (tmp_path/'result.json').write_text(json.dumps({'sources':rows,'sort_states':states,'errors':errors}))
            print(json.dumps({'sources':[(r['demo'],len(r['sources'][0]['content'])) for r in rows], 'sort_states':states}))
            assert len(states[0]['scores']) == 4
            assert states[1]['scores'] == sorted(states[0]['scores'])
            assert states[2]['scores'] == sorted(states[0]['scores'], reverse=True)
            assert states[3]['names'] == states[0]['names']
            assert [s['aria_sort'] for s in states[1:3]] == ['ascending','descending']
        finally:
            context.close()
            browser.close()


def evidence(html, selector="button", status="ok"):
    return ({"observation_evidence": [{"state_id": "path__step_1"}]},
            {"exploration_paths": [{"id": "path", "steps": [{"status": status,
                "action": {"selector": selector}, "state": {"html": html}}]}]})


def test_region_uses_actual_action_ownership_not_card_title():
    card, observation = evidence('<section id="wrong"></section><div class="code-box" id="demo">'
                                 '<section><button>Expand</button></section></div>')
    card["title"] = "wrong"
    regions = card_regions(card, observation)
    assert len(regions) == 1
    assert regions[0]["region_selector"] == '[id="demo"]'


def test_ambiguous_failed_and_absent_evidence_are_not_sources():
    for html, status in [("<button>A</button><button>B</button>", "ok"),
                         ("<button>A</button>", "error"), ("<div/>", "ok")]:
        assert card_regions(*evidence(html, status=status)) == []


def test_slice_preserves_source_text_and_unverified_status(tmp_path):
    source = "import React from 'react';\nexport default () => <div/>;\n"
    row = _write_slice(tmp_path, source, kind="page_example", language="tsx",
        url="https://example.org/demo", region={"region_selector": "#demo", "state_id": "s"}, index=0)
    assert row["source_kind"] == "page_example"
    assert row["standalone_verified"] is False
    assert row["end_line"] == 2
    assert next(tmp_path.glob("*.tsx")).read_text() == source


def test_idless_region_and_each_state_are_located_without_title_guessing():
    card, observation = evidence('<main id="app"><section><button>A</button></section></main>')
    region = card_regions(card, observation)[0]
    assert region["region_selector"] == '[id="app"] > section:nth-of-type(1)'
    assert region["root_tag"] == "section"


def test_final_pool_retains_reference_sources_and_limitations():
    card = {"capability_id": "select", "summary": "Select a row", "visible_result": "Row is selected",
        "source_seed_id": "test", "source_url": "https://example.org", "source_slices": [
            {"content": "button.onclick=selectRow;", "source_kind": "inline_event_attribute"}],
        "source_reference_policy": {"standalone_verified": False, "dependency_closure": "partial"}}
    result = compact_live_card(card)
    assert result["source_slices"] == card["source_slices"]
    assert result["source_reference_policy"] == card["source_reference_policy"]


def test_source_reload_failure_keeps_cited_dom(tmp_path, monkeypatch):
    import json
    from playwright.sync_api import Page
    from inspiration_library.live_component_sources import capture_component_sources
    def fail_navigation(*args, **kwargs):
        raise TimeoutError('controlled reload failure')
    monkeypatch.setattr(Page, 'goto', fail_navigation)
    card, observation = evidence('<section id="demo"><button>Chosen</button></section>')
    card.update(capability_id='demo', source_seed_id='demo', source_url='https://example.org')
    observation['entry_url'] = 'https://example.org'
    result = capture_component_sources({'source_url':'https://example.org','capabilities':[card]},
                                       observation, tmp_path/'capture', max_regions=1)
    assert 'Chosen' in result['capabilities'][0]['source_slices'][0]['content']
    metadata = json.loads((tmp_path/'capture/region_1/metadata.json').read_text())
    assert 'controlled reload failure' in metadata['capture_error']


def test_public_sources_reject_non_source_links():
    from inspiration_library.live_component_sources import public_example_sources
    class Locator:
        def locator(self, *args): return self
        def evaluate_all(self, *args): return [
            'https://github.com.evil.test/a/b/edit/master/a.tsx',
            'https://github.com/a/b/edit/master/readme.md',
            'https://github.com/a/b/issues/1', 'http://localhost/private.tsx']
    assert public_example_sources(Locator(), 'https://example.org') == []


def test_embedded_demo_urls_are_recorded_not_implicitly_explored(tmp_path):
    from playwright.sync_api import sync_playwright
    from inspiration_library.production_browser import serve_project, _launch_browser, _snapshot
    (tmp_path/'index.html').write_text('<iframe id="demo" src="demo.html"></iframe>'
        '<iframe hidden src="tracking.html"></iframe>')
    (tmp_path/'demo.html').write_text('<input placeholder="Inside demo">')
    with serve_project(tmp_path) as url, sync_playwright() as pw:
        browser = _launch_browser(pw)
        try:
            page = browser.new_page()
            page.goto(url)
            state = _snapshot(page)
            assert state['embedded_documents'] == [{'url':url.replace('index.html','demo.html'),
                'selector':'#demo','title':'','same_origin':True}]
            assert not state['interactive']
        finally:
            browser.close()


def test_readonly_browser_blocks_get_form_submission(tmp_path):
    from playwright.sync_api import sync_playwright
    from inspiration_library.production_browser import _launch_browser, _new_page, serve_project
    (tmp_path / "index.html").write_text('<form action="/submitted"><button>Send</button></form>')
    with serve_project(tmp_path) as url, sync_playwright() as pw:
        browser = _launch_browser(pw)
        context, page = _new_page(browser, viewport={"width":800,"height":600},
            remote_requests=[], console_errors=[], page_errors=[], network_mode="online_readonly", entry_url=url)
        requests = []
        page.on("request", lambda req: requests.append(req.url))
        try:
            page.goto(url)
            page.locator("button").click()
            page.evaluate("document.forms[0].submit(); document.forms[0].requestSubmit();")
            page.wait_for_timeout(100)
            assert page.url == url
            assert not any("/submitted" in request for request in requests)
        finally:
            context.close()
            browser.close()


def test_real_browser_reference_capture(tmp_path):
    """Isolated fixture only: no public URL or LLM; exercises the real CDP and output path."""
    from playwright.sync_api import sync_playwright
    from inspiration_library.production_browser import _launch_browser, serve_project
    from inspiration_library.live_component_sources import capture_component_sources
    from pathlib import Path
    import json

    (tmp_path / "index.html").write_text('''<!doctype html><html><head><style>
      :root { --ink: #123456; } .wrapper { color: var(--ink); }
      button { border: 2px solid red; } .unrelated { color: magenta; }
      @media(min-width:1px) { section { padding: 10px; } }
      </style></head><body><main id="app" class="wrapper"><section>
      <h2>Local component</h2><button id="choose" onclick="return helperToggle(this);">Choose</button>
      <img src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=">
      </section></main><aside class="unrelated">Unrelated content</aside>
      <script>function helperToggle(node){node.toggleAttribute('data-mode');}
      document.querySelector('#choose').addEventListener('click', function chooseItem(){
        this.textContent = this.textContent === 'Choose' ? 'Selected' : 'Choose';
      }); document.addEventListener('click', function shouldStayShared(){return true;});</script>
      </body></html>''')
    with serve_project(tmp_path) as url:
        with sync_playwright() as pw:
            browser = _launch_browser(pw)
            page = browser.new_page()
            # All test traffic is confined to the fixture origin.
            page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(url.rsplit('/',1)[0])
                       else route.abort())
            page.goto(url)
            before = page.content()
            page.locator("#choose").click()
            assert page.locator("#choose").inner_text() == "Selected"
            after = page.content()
            page.locator("#choose").click()
            reverted = page.content()
            browser.close()
        card, observation = evidence(after, selector="#choose")
        card.update(capability_id="fixture", summary="Choose an item", visible_result="Selected",
                    source_seed_id="fixture", source_url=url)
        observation.update(entry_url=url)
        path = observation["exploration_paths"][0]
        path["before"] = {"html": before}
        path["steps"].append({"status":"ok", "action":{"selector":"#choose"}, "state":{"html":reverted}})
        second = {**card, "capability_id":"fixture_reverted", "observation_evidence":[{"state_id":"path__step_2"}]}
        result = capture_component_sources({"source_url":url,"capabilities":[card,second]},
                                           observation, tmp_path / "capture", max_regions=1)
    cards = result["capabilities"]
    first_slices = cards[0]["source_slices"]
    css = next(s["content"] for s in first_slices if s["source_kind"] == "runtime_matched_css")
    assert "--ink" in css and "@media" in css and "magenta" not in css
    handlers = [s for s in first_slices if s["source_kind"] == "registered_event_listener"]
    assert any("chooseItem" in s["content"] for s in handlers)
    assert all("shouldStayShared" not in s["content"] for s in handlers)
    assert any(s["source_kind"] == "referenced_global_function" and "toggleAttribute" in s["content"]
               for s in first_slices)
    for item, text, state in [(cards[0],">Selected<","path__step_1"),
                              (cards[1],">Choose<","path__step_2")]:
        dom = next(s for s in item["source_slices"] if s["source_kind"] == "runtime_dom")
        assert text in dom["content"] and "Unrelated content" not in dom["content"]
        assert dom["evidence_state_id"] == state
        assert Path(dom["path"]).read_text() == dom["content"]
        assert item["source_reference_policy"]["standalone_verified"] is False
    metadata = json.loads((tmp_path / "capture/region_1/metadata.json").read_text())
    assert metadata["shared_listeners"]
    assert metadata["dependency_closure"] == "partial"
    assert not list((tmp_path / "capture").rglob("*.gif"))


@pytest.mark.skipif(os.environ.get("WEBCODING_PUBLIC_REFERENCE_PROBE") != "1",
                    reason="Explicit bounded physical-host probe only")
def test_public_business_page_reference(tmp_path):
    """Technical source-mapping probe, not an LLM-mined or accepted capability card."""
    import json
    from playwright.sync_api import sync_playwright
    from inspiration_library.production_browser import _launch_browser, _new_page
    from inspiration_library.live_component_sources import capture_component_sources

    url = "https://www.calculator.net/bmi-calculator.html"
    with sync_playwright() as pw:
        browser = _launch_browser(pw, proxy=os.environ.get("WEBCODING_BROWSER_PROXY"))
        context, page = _new_page(browser, viewport={"width":1440,"height":1000},
            remote_requests=[], console_errors=[], page_errors=[], network_mode="online_readonly", entry_url=url)
        try:
            navigation_requests = []
            page.on("request", lambda request: navigation_requests.append(request.url)
                    if request.is_navigation_request() and request.frame == page.main_frame else None)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_function("document.querySelector('#ctype')?.value === 'metric'", timeout=15000)
            before = page.content()
            selector = "#topmenu li:first-child"
            page.locator(selector).click()
            page.wait_for_function("document.querySelector('#ctype')?.value === 'standard'", timeout=5000)
            assert page.locator("#standardheightweight").is_visible()
            assert not page.locator("#metricheightweight").is_visible()
            assert navigation_requests == [url], "Unit tab unexpectedly submitted a form/navigation"
            after = page.content()
            page.screenshot(path=str(tmp_path / "public_after.png"))
        finally:
            context.close()
            browser.close()
    card, observation = evidence(after, selector=selector)
    card.update(capability_id="diagnostic_units", summary="Diagnostic unit selector reference",
                visible_result="Unit input switched to standard", source_seed_id="diagnostic_only", source_url=url)
    observation.update(entry_url=url)
    observation["exploration_paths"][0]["before"] = {"html":before}
    result = capture_component_sources({"source_url":url,"capabilities":[card]}, observation,
                                       tmp_path / "reference", max_regions=1)
    result["diagnostic_only"] = True
    (tmp_path / "reference_result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
    kinds = {s["source_kind"] for s in result["capabilities"][0]["source_slices"]}
    assert "runtime_dom" in kinds and "runtime_matched_css" in kinds
    assert "inline_event_attribute" in kinds or "registered_event_listener" in kinds
    function = next(s for s in result["capabilities"][0]["source_slices"]
                    if s["source_kind"] == "referenced_global_function")
    assert "function popMenu" in function["content"]
    assert "getElementById" in function["content"]
