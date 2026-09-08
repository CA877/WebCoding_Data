from copy import deepcopy
from types import SimpleNamespace

import pytest

from instruction_augmentation import deep_browser_exploration as deep
from instruction_augmentation import production_browser as browser
from instruction_augmentation.dynamic_capability_retrieval import validate_capability_extraction, validate_live_card_evidence
from instruction_augmentation.linear_edit_queries import compact_browser_evidence_for_llm
from scripts.mine_live_url_capability_pool import compact_live_card


def snapshot(text="Ready", checked=False):
    return {"state_sha256": text + str(checked), "visible_text": text, "aria_snapshot": text,
            "interactive": [{"selector": "#row", "tag": "input", "type": "checkbox", "checked": checked}],
            "session_storage": {}, "local_storage": {}}


def observation():
    before = snapshot()
    return {"source_kind": "live_url", "entry_url": "https://example.com/demo", "status": "ok",
            "baseline": before, "mobile_baseline": before,
            "exploration_paths": [{"id": "select", "status": "ok", "before": before,
                "steps": [{"status": "ok", "action": {"action": "check", "selector": "#row"},
                           "state": snapshot("Selected", True)}]}]}


def extraction(state_id="select__step_1"):
    return {"source_url": "https://example.com/demo", "capabilities": [{
        "capability_id": "demo__select", "source_seed_id": "demo", "source_url": "https://example.com/demo",
        "summary": "Select an existing row and show its selection state.", "change_type": "selection",
        "prerequisites": ["rows"], "user_actions": ["check row"], "state_writes": ["selected row"],
        "visible_result": "The row checkbox is visibly selected.",
        "observation_evidence": [{"state_id": state_id, "evidence": "Checkbox changed from false to true."}]}]}


def test_reference_validation_and_pool_retains_evidence():
    item = validate_live_card_evidence(extraction(), observation())["capabilities"][0]
    compact = compact_live_card(item)
    assert compact["observation_evidence"] == item["observation_evidence"]
    assert compact["evidence_reference_status"] == "validated"
    assert not {"behavior_validation_status", "browser_check_status", "visual_evidence_status"} & compact.keys()


@pytest.mark.parametrize("state_id", ["mobile", "invented", "baseline"])
def test_bad_or_static_reference_cannot_prove_interaction(state_id):
    with pytest.raises(ValueError):
        validate_live_card_evidence(extraction(state_id), observation())


def test_failed_action_and_wrong_url_cannot_validate():
    o = observation()
    o["exploration_paths"][0]["steps"][0]["status"] = "error"
    with pytest.raises(ValueError, match="successful"):
        validate_live_card_evidence(extraction(), o)
    o["entry_url"] = "https://example.com/other"
    with pytest.raises(ValueError, match="URL"):
        validate_live_card_evidence(extraction(), o)


def test_empty_online_extraction_can_abstain():
    result = validate_capability_extraction({"seed_summary": "The browser did not establish the target component.",
        "capabilities": [], "business_objects": [], "abstention_reason": "Only the site navigation was observable."},
        seed_id="demo", source_url="https://example.com/demo")
    assert result["admission_status"] == "abstained"


def test_compression_keeps_references_closed():
    o = observation()
    p = o["exploration_paths"][0]
    p["steps"] = [{"status": "ok", "action": {"action": "click", "selector": "#row"},
                   "state": snapshot(f"Result {i}", bool(i % 2))} for i in range(25)]
    c = deep.compact_live_browser_evidence_for_llm(o, include_selectors=False)
    ids = {row["delta_id"] for row in c["state_delta_catalog"]}
    assert len(ids) <= 12
    assert all(ref in ids for row in c["transitions"] for ref in row["state_delta_refs"])
    assert c["image_input"] == "selected_state_screenshots_when_available"


def test_fresh_page_background_changes_not_attributed_to_action():
    o = observation()
    same = snapshot("New asynchronous background")
    same["session_storage"] = {"tracking": "new-page"}
    o["exploration_paths"][0]["before"] = same
    o["exploration_paths"][0]["steps"][0]["state"] = deepcopy(same)
    c = compact_browser_evidence_for_llm(o)
    assert c["state_delta_catalog"] == []


def test_readonly_control_uses_click_or_skips():
    ctrl = {"selector": "#select", "tag": "input", "type": "text", "readonly": True}
    assert deep._browser_action_for_control(ctrl) is None
    assert deep._browser_action_for_control({**ctrl, "role": "combobox"})["action"] == "click"


def test_navigation_failure_preserves_other_paths(tmp_path, monkeypatch):
    class Page:
        def __init__(self, fail=False): self.fail = fail
        def goto(self, *args, **kwargs):
            if self.fail: raise TimeoutError("navigation timeout")
        def wait_for_timeout(self, *args): pass
    class Manager:
        def __enter__(self): return None
        def __exit__(self, *args): pass
    pages = iter([Page(), Page(), Page(True), Page()])
    monkeypatch.setattr(browser, "sync_playwright", Manager)
    monkeypatch.setattr(browser, "_launch_browser", lambda *args, **kwargs: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(browser, "_new_page", lambda *args, **kwargs: (SimpleNamespace(close=lambda: None), next(pages)))
    monkeypatch.setattr(browser, "_snapshot", lambda page: snapshot())
    monkeypatch.setattr(browser, "_capture_screenshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(browser, "_write_dom_ax_states", lambda *args: None)
    o = browser.observe_url("https://example.com/demo", tmp_path,
        exploration_plan={"paths": [{"id": "fails", "actions": []}, {"id": "works", "actions": []}]})
    assert o["status"] == "partial"
    assert [p["status"] for p in o["exploration_paths"]] == ["error", "ok"]
    assert (tmp_path / "observation.json").exists()


def test_screenshot_inputs_require_real_state_and_file(tmp_path):
    from instruction_augmentation.dynamic_capability_retrieval import live_screenshot_inputs
    from PIL import Image
    file = tmp_path / "state.png"
    Image.new("RGB", (10, 10), "red").save(file)
    o = observation()
    o['baseline']['screenshot_path'] = str(file)
    o['exploration_paths'][0]['steps'][0]['state']['screenshot_path'] = str(file)
    inputs = live_screenshot_inputs(o)
    assert {r['state_id'] for r in inputs} >= {'baseline', 'select__step_1'}
    assert len(live_screenshot_inputs(o, limit=1)) == 1
    o['baseline']['screenshot_path'] = str(tmp_path / 'absent.png')
    assert 'baseline' not in {r['state_id'] for r in live_screenshot_inputs(o)}


def test_full_resume_preserves_failed_source_attempt(tmp_path, monkeypatch):
    """Storage/control-flow test with cached records; no LLM semantic evaluation."""
    import json
    import sys
    from scripts import mine_live_url_capability_pool as miner
    from instruction_augmentation import live_component_sources as sources
    run = tmp_path/'run'
    manifest = tmp_path/'sources.jsonl'
    manifest.write_text(json.dumps({'seed_id':'demo','entry_url':'https://example.com/demo'}))
    monkeypatch.setenv('DOC_API_KEY', 'unused-no-network')
    monkeypatch.setattr(sys, 'argv', ['miner','--sources',str(manifest),'--run-dir',str(run)])
    def cached_observation(**kwargs):
        path = run/'extractions/demo.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(extraction()))
        return observation()
    monkeypatch.setattr(miner, 'deep_explore_url', cached_observation)
    def never_call_llm(**kwargs):
        raise AssertionError('Cached resume must not call LLM')
    monkeypatch.setattr(miner, 'extract_seed_capabilities', never_call_llm)
    attempts = []
    def capture(item, observed, directory, **kwargs):
        directory.mkdir()
        attempts.append(directory)
        (directory/'partial.txt').write_text('preserved')
        if len(attempts) == 1:
            raise RuntimeError('source worker interrupted')
        return item
    monkeypatch.setattr(sources, 'capture_component_sources', capture)
    with pytest.raises(RuntimeError, match='interrupted'):
        miner.main()
    assert miner.main() == 0
    assert attempts[0] != attempts[1]
    assert (attempts[0]/'partial.txt').read_text() == 'preserved'
    assert (run/'capability_pool.jsonl').is_file()
