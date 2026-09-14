from copy import deepcopy

import pytest

from inspiration_library import deep_browser_exploration as deep
from inspiration_library import production_browser as browser
from inspiration_library.dynamic_capability_retrieval import validate_capability_extraction, validate_live_card_evidence
from inspiration_library.linear_edit_queries import compact_browser_evidence_for_llm
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


def test_full_resume_preserves_failed_source_attempt(tmp_path, monkeypatch):
    """Storage/control-flow test with cached records; no LLM semantic evaluation."""
    import json
    import sys
    from scripts import mine_live_url_capability_pool as miner
    from inspiration_library import live_component_sources as sources
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
