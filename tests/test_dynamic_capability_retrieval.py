from __future__ import annotations

import json

import pytest

from inspiration_library.dynamic_capability_retrieval import (
    build_round_retrieval_query,
    capability_embedding_text,
    extract_seed_capabilities,
    merge_capability_pool,
    pool_snapshot_sha256,
    rank_capabilities,
    resolve_round_source,
    round_stable_context,
    validate_capability_extraction,
    validate_dynamic_sequence,
    validate_round_selection,
)


def _extraction(seed_id: str = "seed-a") -> dict:
    return {
        "seed_summary": "A local item dashboard with filtering and stable item identifiers.",
        "business_objects": [
            {"name": "item", "evidence": "The source renders six item cards with data-item-id."}
        ],
        "capabilities": [
            {
                "local_id": "filter_items",
                "name": "Filter visible items",
                "family": "search_filter_sort",
                "summary": "Filter the existing item collection and update the visible result count.",
                "prerequisites": ["a collection of items", "a category field"],
                "user_actions": ["choose one category from the filter"],
                "state_reads": ["item collection", "active category"],
                "state_writes": ["visible item identifiers"],
                "visible_result": "Only matching item cards and the matching count remain visible.",
                "source_evidence": [
                    {"path": "script.js", "evidence": "applyFilter reads category and hides cards."}
                ],
                "browser_checks": [],
            },
            {
                "local_id": "open_detail",
                "name": "Open item details",
                "family": "detail_navigation",
                "summary": "Open a detail surface for one stable item and return to the list.",
                "prerequisites": ["stable item identifiers", "item detail fields"],
                "user_actions": ["open one item and return"],
                "state_reads": ["selected item identifier"],
                "state_writes": ["active detail identifier"],
                "visible_result": "The selected item details become visible.",
                "source_evidence": [
                    {"path": "script.js", "evidence": "openDetail renders the selected record."}
                ],
                "browser_checks": [],
            },
        ],
    }


def test_live_url_capability_extraction_records_url_provenance() -> None:
    payload = _extraction("live-calendar")
    for capability in payload["capabilities"]:
        capability["observation_evidence"] = [
            {
                "state_id": "baseline_to_selected",
                "evidence": "The saved browser state shows the selected value and its visible result.",
            }
        ]
        capability.pop("source_evidence", None)

    extracted = validate_capability_extraction(
        payload,
        seed_id="live-calendar",
        source_url="https://example.com/calendar",
    )

    assert extracted["source_kind"] == "live_url"
    assert extracted["source_url"] == "https://example.com/calendar"
    assert "source_project" not in extracted
    assert all(row["source_kind"] == "live_url" for row in extracted["capabilities"])


def test_structural_role_wrapper_is_losslessly_normalized():
    payload = _extraction()
    payload["capabilities"][0]["prerequisites"] = [{"role": "item collection"}]
    result = validate_capability_extraction(payload, seed_id="test", source_project="/test")
    assert result["capabilities"][0]["prerequisites"] == ["item collection"]
    payload["capabilities"][0]["prerequisites"] = [{"role": "item collection", "invent": True}]
    with pytest.raises(ValueError):
        validate_capability_extraction(payload, seed_id="test", source_project="/test")


def _verified_bank() -> dict:
    return {
        "schema_version": "webcoding-donor-capability-bank-v1",
        "capabilities": [
            {
                "id": "dialog_focus_lifecycle",
                "summary": "Give an existing dialog a complete keyboard focus lifecycle.",
                "prerequisites": ["an existing dialog", "a stable trigger"],
                "outputs": ["modal focus scope", "restored trigger focus"],
                "user_actions": ["open and close the dialog"],
                "verification": ["focus returns to the trigger"],
                "donor_evidence": {
                    "source_project": "/verified/dialog",
                    "verification": "/verified/dialog/check.json",
                    "case_id": "dialog-case",
                },
            }
        ],
    }


def _round(index: int, capability_id: str, family: str, dependencies: list[str]) -> dict:
    return {
        "edit_index": index,
        "edit_id": f"q{index}",
        "source_version": f"s{index - 1}",
        "target_version": f"s{index}",
        "pool_snapshot_sha256": "pool-sha",
        "retrieved_capability_ids": [capability_id, "fallback-card"],
        "selected_capability_id": capability_id,
        "selected_family": family,
        "selection_reason": "The host contains every required local object and lacks the visible result.",
        "prerequisite_mapping": [
            {
                "prerequisite": "stable local items",
                "host_evidence": "The current source renders stable item identifiers.",
            }
        ],
        "instruction": (
            f"Add visible behavior {index} to the existing item workspace. Users must be able to "
            "perform the action and immediately see the resulting item state while all existing "
            "search and detail behavior remains available."
        ),
        "depends_on": dependencies,
        "requires": [
            {
                "state": (
                    f"visible_state_{dependencies[0][1:]}"
                    if dependencies
                    else "seed item state"
                ),
                "source": dependencies[0] if dependencies else "seed",
                "evidence": "The named state is available in the current linear source version.",
            }
        ],
        "produces": [
            {
                "state": f"visible_state_{index}",
                "value_shape": "stable item identifiers",
                "scope": "page",
                "persistence": "memory",
                "observable": "item workspace",
            }
        ],
        "preserve": ["existing search and detail behavior"],
        "acceptance": ["The user action changes the visible item state."],
        "source_gap_checks": [
            {
                "id": f"q{index}_missing_behavior",
                "setup_action_count": 0,
                "actions": [],
                "assertions": [
                    {"type": "visible", "selector": f"#new-behavior-{index}"}
                ],
            }
        ],
    }


def _observation() -> dict:
    baseline = {
        "title": "Item workspace",
        "url": "http://127.0.0.1/index.html",
        "visible_text": "Items Search",
        "html": "<html><body><main><input aria-label='Search'></main></body></html>",
        "html_length": 70,
        "html_truncated": False,
        "interactive": [{"selector": "input", "tag": "input", "aria_label": "Search"}],
        "structures": [{"tag": "main", "text": "Items Search"}],
        "local_storage": {},
        "session_storage": {},
        "aria_snapshot": "- main:\n  - searchbox \"Search\"",
        "horizontal_overflow": False,
        "state_sha256": "baseline-sha",
    }
    return {
        "status": "ok",
        "baseline": baseline,
        "exploration_paths": [
            {
                "id": "open_items",
                "status": "ok",
                "steps": [
                    {
                        "status": "ok",
                        "action": {"action": "click", "selector": "#items"},
                        "state": {**baseline, "url": "http://127.0.0.1/#items", "state_sha256": "items-sha"},
                    }
                ],
                "after": {**baseline, "url": "http://127.0.0.1/#items", "state_sha256": "items-sha"},
            }
        ],
        "remote_requests": [],
        "console_errors": [],
        "page_errors": [],
    }


def test_merges_observed_and_historical_capability_inspirations_without_donor_gate() -> None:
    extracted = validate_capability_extraction(
        _extraction(), seed_id="seed-a", source_project="/seed-a"
    )
    pool = merge_capability_pool([extracted], _verified_bank())

    assert len(pool) == 3
    assert {row["library_origin"] for row in pool} == {
        "observed_seed_capability",
        "historical_capability_card",
    }
    assert all(row["library_role"] == "capability_inspiration" for row in pool)
    assert all("verification_status" not in row for row in pool)
    assert all("verification_evidence" not in row for row in pool)
    assert any(row["capability_id"] == "seed-a__filter_items" for row in pool)
    observed = next(
        row for row in pool if row["library_origin"] == "observed_seed_capability"
    )
    historical = next(
        row for row in pool if row["library_origin"] == "historical_capability_card"
    )
    assert "search_filter_sort" in capability_embedding_text(observed)
    assert historical["source_lineage"]["case_id"] == "dialog-case"
    assert len(pool_snapshot_sha256(pool)) == 64


def test_preserves_provider_browser_check_prose_without_claiming_it_is_executable() -> None:
    payload = _extraction()
    payload["capabilities"][0]["state_reads"] = []
    payload["capabilities"][0]["state_writes"] = []
    payload["capabilities"][0]["browser_checks"] = [
        {"selector": "#item-filter", "assertion": "exists and is visible"}
    ]

    extracted = validate_capability_extraction(
        payload, seed_id="seed-a", source_project="/seed-a"
    )
    card = extracted["capabilities"][0]

    assert card["state_reads"] == []
    assert card["state_writes"] == []
    assert card["state_write_status"] == "visible_effect_only"
    assert card["browser_checks"] == []
    assert card["browser_check_status"] == "needs_compilation"
    assert card["reported_browser_checks"] == [
        {"selector": "#item-filter", "assertion": "exists and is visible"}
    ]


def test_accepts_browser_observation_evidence_without_source_paths() -> None:
    payload = _extraction()
    for capability in payload["capabilities"]:
        capability.pop("source_evidence")
        capability["observation_evidence"] = [
            {
                "state_id": "baseline",
                "evidence": "The saved DOM and accessibility tree expose this user-visible behavior.",
            }
        ]
    extracted = validate_capability_extraction(
        payload, seed_id="seed-a", source_project="/seed-a"
    )
    assert extracted["evidence_basis"] == "browser_dom_ax_states"
    assert extracted["capabilities"][0]["observation_evidence"][0]["state_id"] == "baseline"
    assert extracted["capabilities"][0]["source_evidence"] == []


def test_capability_extraction_has_no_card_count_ceiling() -> None:
    payload = _extraction()
    template = payload["capabilities"][0]
    payload["capabilities"] = [
        {
            **template,
            "local_id": f"complete_feature_{index}",
            "name": f"Complete feature {index}",
        }
        for index in range(13)
    ]

    extracted = validate_capability_extraction(
        payload, seed_id="seed-a", source_project="/seed-a"
    )

    assert len(extracted["capabilities"]) == 13


def test_new_card_shape_records_change_kind_future_use_and_source_anchors() -> None:
    payload = _extraction()
    for capability in payload["capabilities"]:
        capability["change_type"] = "state_propagation"
        capability["future_uses"] = ["a later Edit can consume the selected item ids"]
        capability["source_anchors"] = ["Search", "result-count"]
        capability.pop("source_evidence")
        capability["observation_evidence"] = [
            {
                "state_id": "baseline",
                "evidence": "The saved browser state shows the trigger and synchronized result.",
            }
        ]

    extracted = validate_capability_extraction(
        payload, seed_id="seed-a", source_project="/seed-a"
    )

    card = extracted["capabilities"][0]
    assert card["change_type"] == "state_propagation"
    assert card["future_uses"] == [
        "a later Edit can consume the selected item ids"
    ]
    assert card["source_anchors"] == ["Search", "result-count"]


def test_visual_or_responsive_card_does_not_require_a_user_action() -> None:
    payload = _extraction()
    payload["capabilities"][0]["change_type"] = "responsive_layout"
    payload["capabilities"][0]["user_actions"] = []

    extracted = validate_capability_extraction(
        payload, seed_id="seed-a", source_project="/seed-a"
    )

    assert extracted["capabilities"][0]["user_actions"] == []


def test_retrieval_excludes_current_host_and_used_capabilities() -> None:
    pool = [
        {"capability_id": "host-card", "source_seed_id": "host", "embedding": [1.0, 0.0]},
        {"capability_id": "used-card", "source_seed_id": "donor-a", "embedding": [0.9, 0.1]},
        {"capability_id": "new-card", "source_seed_id": "donor-b", "embedding": [0.8, 0.2]},
        {"capability_id": "other-card", "source_seed_id": "donor-c", "embedding": [0.0, 1.0]},
    ]
    ranked = rank_capabilities(
        query_vector=[1.0, 0.0],
        embedded_pool=pool,
        host_seed_id="host",
        used_capability_ids={"used-card"},
        top_k=2,
    )

    assert [row["capability_id"] for row in ranked] == ["new-card", "other-card"]
    assert ranked[0]["similarity"] > ranked[1]["similarity"]


def test_live_source_rejects_targets_with_wrong_schema(tmp_path) -> None:
    from scripts.mine_live_url_capability_pool import load_sources
    path = tmp_path / "sources.jsonl"
    path.write_text(json.dumps({"seed_id":"x", "entry_url":"https://example.com", "target_edit_types":"Tabs"}))
    with pytest.raises(ValueError, match="array"):
        load_sources(path)


def test_live_exploration_passes_targets_and_blocks_stale_cache(tmp_path, monkeypatch) -> None:
    import inspiration_library.deep_browser_exploration as deep
    captured = {}
    original = deep._deep_explore
    def capture(**kwargs):
        captured.update(kwargs)
        return {}
    monkeypatch.setattr(deep, "_deep_explore", capture)
    targets = {"target_edit_types": ["Undo Redo"]}
    deep.deep_explore_url(entry_url="https://example.com", output_dir=tmp_path,
                          client=None, request_prefix="x", exploration_targets=targets)
    assert captured["exploration_targets"] == targets
    (tmp_path / "exploration_targets.json").write_text(json.dumps({"target_edit_types":["Tabs"]}))
    with pytest.raises(ValueError, match="targets changed"):
        original(observe=None, output_dir=tmp_path, client=None, request_prefix="x", exploration_targets=targets)


def test_round_query_changes_after_each_linear_edit() -> None:
    host_profile = validate_capability_extraction(
        _extraction("host"), seed_id="host", source_project="/host"
    )
    q1 = build_round_retrieval_query(host_profile=host_profile, prior_edits=[], edit_index=1)
    q2 = build_round_retrieval_query(
        host_profile=host_profile,
        prior_edits=[_round(1, "card-a", "selection", [])],
        edit_index=2,
    )

    assert "CURRENT SOURCE VERSION: s0" in q1
    assert "CURRENT SOURCE VERSION: s1" in q2
    assert "visible_state_1" in q2
    assert q1 != q2


def test_round_source_requires_each_prior_target_to_be_materialized(tmp_path) -> None:
    seed = tmp_path / "seed"
    versions = tmp_path / "accepted_versions"
    seed.mkdir()
    assert resolve_round_source(
        seed_project=seed, accepted_versions_dir=versions, edit_index=1
    ) == seed
    assert resolve_round_source(
        seed_project=seed, accepted_versions_dir=versions, edit_index=2
    ) is None
    s1 = versions / "s1"
    s1.mkdir(parents=True)
    assert resolve_round_source(
        seed_project=seed, accepted_versions_dir=versions, edit_index=2
    ) == s1


def test_round_selection_must_choose_from_that_round_retrieval() -> None:
    payload = _round(2, "card-a", "selection", ["q1"])
    normalized = validate_round_selection(
        payload,
        edit_index=2,
        pool_snapshot="pool-sha",
        retrieved_capability_ids=["card-a", "fallback-card"],
        prior_edits=[_round(1, "card-z", "filter", [])],
    )
    assert normalized["selected_capability_id"] == "card-a"
    assert normalized["source_gap_checks"][0]["setup_action_count"] == 0

    decorated = json.loads(json.dumps(payload))
    decorated["edit_index"] = 0
    decorated["edit_id"] = "semantic-edit-name"
    canonical = validate_round_selection(
        decorated,
        edit_index=2,
        pool_snapshot="pool-sha",
        retrieved_capability_ids=["card-a", "fallback-card"],
        prior_edits=[_round(1, "card-z", "filter", [])],
    )
    assert canonical["edit_index"] == 2
    assert canonical["edit_id"] == "q2"
    assert canonical["provider_control_fields"] == {
        "edit_index": 0,
        "edit_id": "semantic-edit-name",
    }

    implementation_source = json.loads(json.dumps(payload))
    implementation_source["requires"][0]["source"] = "app.js"
    canonical_source = validate_round_selection(
        implementation_source,
        edit_index=2,
        pool_snapshot="pool-sha",
        retrieved_capability_ids=["card-a", "fallback-card"],
        prior_edits=[_round(1, "card-z", "filter", [])],
    )
    assert canonical_source["requires"][0]["source"] == "q1"
    assert canonical_source["requires"][0]["provider_source"] == "app.js"

    user_facing_selector = json.loads(json.dumps(payload))
    user_facing_selector["instruction"] += (
        " Provide a visible selector so users can load one saved view."
    )
    assert validate_round_selection(
        user_facing_selector,
        edit_index=2,
        pool_snapshot="pool-sha",
        retrieved_capability_ids=["card-a", "fallback-card"],
        prior_edits=[_round(1, "card-z", "filter", [])],
    )["edit_id"] == "q2"

    invalid = json.loads(json.dumps(payload))
    invalid["selected_capability_id"] = "not-retrieved"
    with pytest.raises(ValueError, match="retrieved in this round"):
        validate_round_selection(
            invalid,
            edit_index=2,
            pool_snapshot="pool-sha",
            retrieved_capability_ids=["card-a"],
            prior_edits=[_round(1, "card-z", "filter", [])],
        )


def test_round_selection_can_require_source_gap_checks() -> None:
    payload = _round(1, "card-a", "selection", [])
    payload.pop("source_gap_checks")
    with pytest.raises(ValueError, match="source_gap_checks"):
        validate_round_selection(
            payload,
            edit_index=1,
            pool_snapshot="pool-sha",
            retrieved_capability_ids=["card-a"],
            prior_edits=[],
            require_source_gap_checks=True,
        )


def test_dynamic_sequence_requires_five_distinct_retrieval_events_and_families() -> None:
    rounds = [
        _round(1, "card-a", "filter", []),
        _round(2, "card-b", "accessibility", []),
        _round(3, "card-c", "summary", ["q1"]),
        _round(4, "card-d", "navigation", []),
        _round(5, "card-e", "summary", ["q3"]),
    ]
    for index, row in enumerate(rounds, 1):
        row["retrieval"] = {
            "request_id": f"retrieve__q{index}",
            "query_sha256": f"query-sha-{index}",
            "pool_snapshot_sha256": "pool-sha",
        }
    result = validate_dynamic_sequence(
        {"seed_id": "host", "pool_snapshot_sha256": "pool-sha", "edits": rounds}
    )
    assert result["edit_count"] == 5
    assert result["distinct_family_count"] == 4
    assert result["retrieval_event_count"] == 5

    broken = json.loads(json.dumps({"seed_id": "host", "pool_snapshot_sha256": "pool-sha", "edits": rounds}))
    broken["edits"][4]["retrieval"]["request_id"] = "retrieve__q4"
    with pytest.raises(ValueError, match="distinct retrieval event"):
        validate_dynamic_sequence(broken)
