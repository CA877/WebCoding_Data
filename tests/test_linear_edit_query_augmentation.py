from __future__ import annotations

import json
from pathlib import Path
import re

import pytest

from inspiration_library.linear_edit_queries import (
    apply_exact_patches,
    build_seed_pool,
    browser_derived_host_facts,
    choose_sample,
    compact_browser_evidence,
    compact_browser_evidence_for_llm,
    generation_task,
    normalize_repeated_instruction_openings,
    generation_stable_prefix,
    load_json_response,
    validate_edit_sequence,
    validate_quality_audit,
)
from inspiration_library.transfer_evidence import RankedEffect
from scripts.run_linear_edit_query_augmentation import export_queries


def _original_record(instance_id: str) -> dict:
    return {
        "instance_id": instance_id,
        "instruction": f"Build {instance_id}",
        "page_type": "sp",
        "response": [
            {"path": "index.html", "code": "<main>seed</main>"},
            {"path": "app.js", "code": "const items = [];"},
        ],
        "metadata": {"prompt_tokens": 1000},
    }


def _review(instance_id: str, *, passing: bool = True) -> dict:
    return {
        "instance_id": instance_id,
        "hard_gate_pass": passing,
        "grade": "A",
        "issues": [] if passing else ["interaction_broken"],
        "total_score": 90,
    }


def _supplement_record(instance_id: str) -> dict:
    return {
        "instance_id": instance_id,
        "instruction": "Repair the provided web project.",
        "page_type": "mp",
        "input_files": [
            {"path": "index.html", "code": "<main>old</main>"},
            {"path": "app.js", "code": "const state = 'old';"},
        ],
        "response": [
            {
                "path": "app.js",
                "search": "const state = 'old';",
                "replace": "const state = 'clean';",
            }
        ],
        "metadata": {"project_pages": ["index.html", "details.html"]},
    }


def _supplement_audit(instance_id: str, *, duplicate: bool = False) -> dict:
    return {
        "instance_id": instance_id,
        "status": "ok",
        "route_kind": "physical",
        "output_duplicate_groups": [["1.png", "2.png"]] if duplicate else [],
    }


def _valid_sequence(edit_count: int = 10) -> dict:
    edits = []
    produced = [
        "saved_items",
        "active_filter",
        "filtered_saved_items",
        "notes",
        "export_rows",
        "sort_order",
        "density_mode",
        "note_summary",
        "focus_target",
        "responsive_columns",
        "reading_mode",
        "keyboard_target",
    ]
    dependencies = [[] for _ in range(edit_count)]
    if edit_count >= 3:
        dependencies[2] = ["q1", "q2"]
    if edit_count >= 5:
        dependencies[4] = ["q3"]
    if edit_count >= 8:
        dependencies[7] = ["q4"]
    requirements = [[{"state": "seed_items", "source": "seed"}] for _ in range(edit_count)]
    if edit_count >= 3:
        requirements[2] = [
            {"state": "saved_items", "source": "q1"},
            {"state": "active_filter", "source": "q2"},
        ]
    if edit_count >= 5:
        requirements[4] = [{"state": "filtered_saved_items", "source": "q3"}]
    if edit_count >= 8:
        requirements[7] = [{"state": "notes", "source": "q4"}]
    opening_verbs = (
        "Implement",
        "Create",
        "Develop",
        "Enhance",
        "Build",
        "Integrate",
        "Upgrade",
        "Add",
        "Introduce",
        "Provide",
        "Design",
        "Extend",
    )
    for index in range(1, edit_count + 1):
        edits.append(
            {
                "edit_index": index,
                "edit_id": f"q{index}",
                "source_version": f"s{index - 1}",
                "target_version": f"s{index}",
                "instruction": (
                    f"{opening_verbs[index - 1]} a complete item-management module in the existing workspace "
                    "using the visible item list and current search area. Let users select an item, save it to "
                    "a named collection, remove it again, and see the affected card and collection count update "
                    "immediately. Provide a clear empty result, duplicate-selection feedback, and a one-click "
                    "reset that restores the original item order without discarding unrelated search text. Keep "
                    "the controls keyboard reachable, expose the selected state accessibly, and adapt the "
                    "collection panel to the narrow mobile layout while preserving all existing item actions."
                ),
                "origin": "host_grounded_gap",
                "donor_capability_id": None,
                "source_gap": "The current workspace cannot complete this visible user goal.",
                "user_value": "Users can complete the related item workflow without manual tracking.",
                "product_fit": "The behavior uses the workspace's existing items and search flow.",
                "requires": requirements[index - 1],
                "produces": [
                    {
                        "state": produced[index - 1],
                        "value_shape": "array of stable item identifiers",
                        "scope": "page",
                        "persistence": "memory",
                        "observable": "visible item workspace",
                    }
                ],
                "depends_on": dependencies[index - 1],
                "dependency_reason": (
                    "Consumes the named prior states to compute the visible result."
                    if dependencies[index - 1]
                    else "Independent of states introduced by earlier edits."
                ),
                "preserve": ["current search behavior"],
                "acceptance": ["The new behavior changes a visible result after a user action."],
            }
        )
        for requirement in edits[-1]["requires"]:
            requirement["evidence"] = "The state is visible in the source or produced by the named prior Edit."
    return {
        "seed_summary": "An item workspace with search and stable item identifiers.",
        "existing_capabilities": ["search items"],
        "edits": edits,
    }


def _accepted_quality_audit() -> dict:
    dimensions = (
        "source_grounding",
        "novelty",
        "product_naturalness",
        "specificity",
        "local_feasibility",
        "preservation",
        "dependency_correctness",
    )
    return {
        "sequence_decision": "accept",
        "sequence_issues": [],
        "edits": [
            {
                "edit_id": f"q{index}",
                "scores": {dimension: 4 for dimension in dimensions},
                "decision": "accept",
                "issues": [],
                "evidence": ["The decision is grounded in the supplied source and browser facts."],
            }
            for index in range(1, 11)
        ],
    }


def _attach_card_assessments(
    payload: dict, cards: list[dict], compatible_ids: set[str]
) -> None:
    payload["card_assessments"] = []
    for card in cards:
        card_id = card["capability_id"]
        requirements = card.get("requires") or card.get("prerequisites") or []
        mappings = [
            {
                "requirement": requirement,
                "host_evidence": "The browser shows matching repeated host objects and the required local state.",
                "evidence_scope": "repeated_record",
            }
            for requirement in requirements
        ]
        if card_id in compatible_ids and not mappings:
            mappings = [
                {
                    "requirement": "No explicit card prerequisite",
                    "host_evidence": "The browser shows a directly compatible local product region and user path.",
                    "evidence_scope": "visible_region",
                }
            ]
        payload["card_assessments"].append(
            {
                "capability_id": card_id,
                "compatible": card_id in compatible_ids,
                "prerequisite_mapping": mappings if card_id in compatible_ids else [],
                "reason": "The host evidence either fully supports or clearly lacks the required object scope.",
            }
        )


def test_apply_exact_patches_requires_one_match() -> None:
    files = {"index.html": "<main>old</main>"}
    assert apply_exact_patches(
        files,
        [{"path": "index.html", "search": "old", "replace": "clean"}],
    )["index.html"] == "<main>clean</main>"
    with pytest.raises(ValueError, match="exactly once"):
        apply_exact_patches(
            {"index.html": "old old"},
            [{"path": "index.html", "search": "old", "replace": "clean"}],
        )


def test_build_seed_pool_uses_only_prior_passes() -> None:
    original_records = [_original_record(f"o-{index}") for index in range(4)]
    reviews = [_review("o-0"), _review("o-1"), _review("o-2"), _review("o-3", passing=False)]
    supplement_records = [_supplement_record("s-0"), _supplement_record("s-1")]
    supplement_audits = [_supplement_audit("s-0"), _supplement_audit("s-1", duplicate=True)]
    pool = build_seed_pool(
        original_records=original_records,
        original_reviews=reviews,
        supplement_records=supplement_records,
        supplement_audits=supplement_audits,
        original_count=2,
        supplement_count=1,
        selection_seed=28,
    )
    assert len(pool) == 3
    assert {row["dataset"] for row in pool} == {"0805", "0805supplement"}
    supplement = next(row for row in pool if row["dataset"] == "0805supplement")
    assert supplement["files"]["app.js"] == "const state = 'clean';"


def test_choose_sample_is_reproducible_and_keeps_provenance() -> None:
    pool = [
        {"seed_id": f"seed-{index}", "dataset": "0805", "files": {"index.html": str(index)}}
        for index in range(20)
    ]
    first = choose_sample(pool, sample_count=10, selection_seed=20260828)
    second = choose_sample(pool, sample_count=10, selection_seed=20260828)
    assert [row["seed_id"] for row in first] == [row["seed_id"] for row in second]
    assert len({row["seed_id"] for row in first}) == 10


def test_generation_prefix_includes_retrieved_donor_snippets_as_hidden_context() -> None:
    capability_bank = {
        "capabilities": [
            {
                "id": "legacy-filter",
                "summary": "Filter a local list.",
                "prerequisites": ["list"],
                "outputs": ["filter state"],
                "verification": ["visible rows change"],
            }
        ]
    }
    retrieved = {
        "capability_id": "history_with_entity_filter",
        "name": "Filterable action history",
        "family": "history",
        "summary": "Keep a visible local action history and filter it by entity.",
        "prerequisites": ["stable local entities"],
        "user_actions": ["change an entity", "filter the history"],
        "state_reads": ["action history"],
        "state_writes": ["active history filter"],
        "visible_result": "Only matching history rows remain visible.",
        "donor_snippets": [
            {
                "snippet_id": "history_with_entity_filter__1",
                "language": "javascript",
                "code": "const visible = history.filter(row => row.entityId === activeId);",
                "sha256": "a" * 64,
            }
        ],
    }

    prefix = generation_stable_prefix(capability_bank, retrieved_cards=(retrieved,))

    assert "history_with_entity_filter" in prefix
    assert "history.filter" in prefix
    assert "legacy-filter" not in prefix
    assert "hidden planning evidence" in prefix


def test_generation_prefix_accepts_minimal_cards_with_framework_source_slices() -> None:
    retrieved = {
        "capability_id": "selection_limit_feedback",
        "change_type": "validation_feedback",
        "summary": "Limit a selection and explain why an additional item cannot be added.",
        "requires": ["a selectable local collection"],
        "user_actions": ["select items until the configured maximum is reached"],
        "produces": ["bounded selection", "visible limit feedback"],
        "visible_result": "The current selection remains unchanged and feedback is shown.",
        "future_uses": ["enable a comparison action after the minimum selection"],
        "source_slices": [
            {
                "slice_id": "selection_limit_feedback__slice_1",
                "path": "src/ComparePanel.tsx",
                "language": "typescript",
                "start_line": 42,
                "end_line": 50,
                "sha256": "b" * 64,
                "content": "if (selected.size >= maxItems) return;",
            }
        ],
    }

    prefix = generation_stable_prefix(
        {"capabilities": []}, retrieved_cards=(retrieved,)
    )

    assert "validation_feedback" in prefix
    assert "ComparePanel.tsx" in prefix
    assert "state_reads" not in prefix


def test_effect_only_planning_task_uses_browser_facts_without_complete_source() -> None:
    seed = {
        "seed_id": "seed-a",
        "dataset": "0805",
        "original_instruction": "Build a local item workspace.",
        "page_type": "sp",
        "prior_quality_evidence": {"grade": "A"},
        "files": {"index.html": "<main>SECRET SOURCE</main>"},
    }
    observation = {
        "status": "ok",
        "dom_summary": {"buttons": ["Filter"]},
        "accessibility_tree": {"role": "main"},
    }

    task = generation_task(seed, observation, include_source=False)

    assert "CURRENT BROWSER EVIDENCE" in task
    assert "\n\nCOMPLETE HOST SOURCE FACTS\n" not in task
    assert "SECRET SOURCE" not in task
    assert "80-120 English words" in task
    assert "standalone, coherent feature module" in task
    assert "semantic-substance test" in task
    assert "never stretch it with generic requirements" in task
    assert "at most one instruction may state one specifically named coexistence" in task
    assert "no opening verb used more than twice" in task
    assert "copies one produces.state from qK character for character" in task
    assert "rather than only once on the page or section" in task
    assert "same user goal and state transition through another control" in task
    assert "Choose dependency positions from the actual content" in task
    assert "putting the relationship only in" in task
    assert "removing the cited prior capability" in task
    assert "never label a hidden dependency as independent" in task
    assert "word and sentence counts are guidance" in task
    assert "exactly one card_assessments row for every supplied card" in task
    assert "Preserve base-object scope and cardinality" in task
    assert "Do not assign retrieved cards to fixed q positions" in task
    assert "Do not repeat a fixed closing checklist" in task
    assert "visual, style, information-organization, or responsive Edit" in task


def test_compact_browser_evidence_does_not_duplicate_or_overgrow_baseline() -> None:
    observation = {
        "status": "ok",
        "baseline": {
            "html": "x" * 20000,
            "aria_snapshot": "a" * 9000,
            "visible_text": "v" * 7000,
            "interactive": [{"tag": "button", "text": str(i)} for i in range(100)],
            "structures": [{"tag": "section", "text": str(i)} for i in range(100)],
            "state_sha256": "baseline",
        },
        "exploration_paths": [],
    }

    compact = compact_browser_evidence(observation)

    assert compact["states"] == []
    assert len(compact["baseline"]["dom_html"]) == 12000
    assert len(compact["baseline"]["aria_snapshot"]) == 7000
    assert len(compact["baseline"]["visible_text"]) == 5000
    assert len(compact["baseline"]["interactive"]) == 100
    assert compact["baseline"]["interactive"][-1]["text"] == "99"
    assert len(compact["structures"]) == 100
    assert compact["structures"][-1]["text"] == "99"


def test_low_cost_browser_evidence_keeps_state_changes_without_repeating_pages() -> None:
    baseline = {
        "state_sha256": "base",
        "url": "http://127.0.0.1/index.html",
        "title": "Items",
        "html": "<main>" + "unchanged markup " * 5000 + "</main>",
        "visible_text": "Items\nSearch items\nUnchanged description",
        "aria_snapshot": '- main\n  - searchbox "Search items"',
        "interactive": [
            {"selector": "#search", "tag": "input", "aria_label": "Search items"}
        ],
        "active_element": {"selector": "body", "tag": "body"},
        "scroll_position": {"x": 0, "y": 0, "max_x": 0, "max_y": 800},
        "record_groups": [
            {
                "parent_selector": "#items",
                "item_tag": "article",
                "item_count": 2,
                "records": [
                    {"selector": "#a", "text": "Alpha", "marker_fields": []},
                    {"selector": "#b", "text": "Beta", "marker_fields": []},
                ],
            }
        ],
        "local_storage": {},
        "session_storage": {},
    }
    saved = {
        **baseline,
        "state_sha256": "saved",
        "visible_text": baseline["visible_text"] + "\nSaved view created",
        "aria_snapshot": baseline["aria_snapshot"] + '\n  - status "Saved view created"',
        "interactive": baseline["interactive"]
        + [{"selector": "#restore", "tag": "button", "text": "Restore view"}],
        "active_element": {"selector": "#restore", "tag": "button"},
        "scroll_position": {"x": 0, "y": 420, "max_x": 0, "max_y": 800},
        "local_storage": {"saved_views": '[{"name":"Urgent"}]'},
    }
    observation = {
        "status": "ok",
        "baseline": baseline,
        "exploration_paths": [
            {
                "id": "save_view",
                "purpose": "Save the current view",
                "status": "ok",
                "steps": [
                    {
                        "action": {"action": "click", "selector": "#save"},
                        "state": saved,
                    }
                ],
                "after": saved,
            }
        ],
    }

    compact = compact_browser_evidence_for_llm(
        observation, include_known_selectors=True
    )
    rendered = json.dumps(compact, ensure_ascii=False)

    assert "dom_html" not in rendered
    assert "Saved view created" in rendered
    assert "saved_views" in rendered
    assert "active_element_after" in rendered
    assert '"y": 420' in rendered
    assert "record_groups" in rendered
    assert "#restore" in rendered
    assert "#search" in compact["known_selectors"]
    assert len(rendered) < 12000


def test_low_cost_browser_evidence_processes_controls_and_transitions_after_old_caps() -> None:
    baseline = {
        "state_sha256": "base",
        "url": "http://127.0.0.1/index.html",
        "visible_text": "base",
        "aria_snapshot": '- main "base"',
        "interactive": [
            {"selector": f"#control-{index}", "tag": "button", "text": str(index)}
            for index in range(50)
        ],
        "structures": [
            {"tag": "section", "id": f"section-{index}", "text": str(index)}
            for index in range(25)
        ],
    }
    observation = {
        "status": "ok",
        "baseline": baseline,
        "exploration_paths": [
            {
                "id": f"path-{index}",
                "status": "ok",
                "steps": [
                    {
                        "action": {"action": "click", "selector": f"#control-{index}"},
                        "state": {
                            **baseline,
                            "state_sha256": f"state-{index}",
                            "visible_text": f"base\nresult-{index}",
                        },
                    }
                ],
            }
            for index in range(35)
        ],
    }

    compact = compact_browser_evidence_for_llm(
        observation, include_known_selectors=True
    )

    assert compact["baseline"]["interactive_control_total"] == 50
    assert compact["baseline"]["interactive_controls"][0]["count"] == 50
    assert (
        compact["baseline"]["interactive_controls"][0]["observed_values"]
        ["selector"]["unique_count"]
        == 50
    )
    assert "#control-49" in compact["known_selectors"]
    assert compact["baseline"]["structures"][0]["count"] == 25
    assert len(compact["transitions"]) == 35
    assert "result-34" in json.dumps(compact["state_delta_catalog"], ensure_ascii=False)


def test_accepted_quality_audit_cannot_keep_edit_or_sequence_issues() -> None:
    clean = _accepted_quality_audit()
    assert validate_quality_audit(clean, seed_id="seed-a")["sequence_decision"] == "accept"

    edit_issue = json.loads(json.dumps(clean))
    edit_issue["edits"][2]["issues"] = ["The product fit is still uncertain."]
    with pytest.raises(ValueError, match="accepted Edit still has quality issues"):
        validate_quality_audit(edit_issue, seed_id="seed-a")

    sequence_issue = json.loads(json.dumps(clean))
    sequence_issue["sequence_issues"] = ["Q4 duplicates Q2."]
    with pytest.raises(ValueError, match="accepted sequence still has quality issues"):
        validate_quality_audit(sequence_issue, seed_id="seed-a")


def test_validate_edit_sequence_requires_linear_versions_and_mixed_dependencies() -> None:
    normalized = validate_edit_sequence(
        _valid_sequence(),
        seed_id="seed-a",
        donor_ids={"persistent_named_filter_views"},
    )
    assert [row["source_version"] for row in normalized["edits"]] == [
        "s0",
        "s1",
        "s2",
        "s3",
        "s4",
        "s5",
        "s6",
        "s7",
        "s8",
        "s9",
    ]
    assert sum(bool(row["depends_on"]) for row in normalized["edits"]) == 3

    branched = json.loads(json.dumps(_valid_sequence()))
    branched["edits"][2]["source_version"] = "s1"
    with pytest.raises(ValueError, match="linear source"):
        validate_edit_sequence(branched, seed_id="seed-a", donor_ids=set())

    all_dependent = json.loads(json.dumps(_valid_sequence()))
    for index in range(1, 10):
        all_dependent["edits"][index]["depends_on"] = [f"q{index}"]
        all_dependent["edits"][index]["requires"] = [
            {
                "state": all_dependent["edits"][index - 1]["produces"][0]["state"],
                "source": f"q{index}",
                "evidence": "The immediately prior Edit produces this named state for the next step.",
            }
        ]
    with pytest.raises(ValueError, match="at least 2 later independent"):
        validate_edit_sequence(all_dependent, seed_id="seed-a", donor_ids=set())


def test_validate_edit_sequence_treats_empty_donor_id_as_absent() -> None:
    payload = _valid_sequence()
    payload["edits"][0]["donor_capability_id"] = ""

    normalized = validate_edit_sequence(payload, seed_id="seed-a", donor_ids=set())

    assert normalized["edits"][0]["donor_capability_id"] is None


@pytest.mark.parametrize("edit_count", [4, 8, 12])
def test_validate_edit_sequence_supports_configured_range(edit_count: int) -> None:
    normalized = validate_edit_sequence(
        _valid_sequence(edit_count),
        seed_id="seed-a",
        donor_ids=set(),
        edit_count=edit_count,
    )

    assert normalized["edit_count"] == edit_count
    assert normalized["edits"][-1]["edit_id"] == f"q{edit_count}"


def test_validate_edit_sequence_supports_adaptive_count() -> None:
    payload = _valid_sequence(8)
    payload["edit_count_reason"] = (
        "Eight distinct modules are supported; additional items would duplicate existing goals."
    )

    normalized = validate_edit_sequence(
        payload,
        seed_id="seed-a",
        donor_ids=set(),
        edit_count=None,
    )

    assert normalized["edit_count"] == 8
    assert normalized["edit_count_reason"].startswith("Eight distinct")


def test_validate_edit_sequence_must_follow_frozen_module_dependencies_and_outputs() -> None:
    payload = _valid_sequence(4)
    payload["dependency_plan"] = ["q3"]
    module_plan = [
        {
            "edit_id": f"q{index}",
            "depends_on": (["q1", "q2"] if index == 3 else []),
            "produces_state": payload["edits"][index - 1]["produces"][0]["state"],
        }
        for index in range(1, 5)
    ]

    normalized = validate_edit_sequence(
        payload,
        seed_id="seed-a",
        donor_ids=set(),
        edit_count=4,
        module_plan=module_plan,
    )

    assert normalized["frozen_module_plan_sha256"]
    broken = json.loads(json.dumps(payload))
    broken["edits"][2]["depends_on"] = ["q1"]
    with pytest.raises(ValueError, match="differs from the frozen module plan"):
        validate_edit_sequence(
            broken,
            seed_id="seed-a",
            donor_ids=set(),
            edit_count=4,
            module_plan=module_plan,
        )


def test_validate_edit_sequence_requires_grounded_quotes_and_reverse_order_evidence() -> None:
    payload = _valid_sequence(4)
    payload["edit_count_reason"] = (
        "Four distinct modules are supported by the supplied Host evidence."
    )
    payload["dependency_plan"] = ["q3"]
    payload["edits"][2]["instruction"] = payload["edits"][2]["instruction"].replace(
        "using the visible item list and current search area.",
        "using the saved items and active filter from the visible item list.",
    )
    for edit in payload["edits"]:
        edit["source_claims"] = [
            {
                "claim": "The Host contains a visible item list.",
                "evidence_quote": "visible item list",
            }
        ]
        for requirement in edit["requires"]:
            if requirement["source"] == "seed":
                requirement["evidence_quote"] = "visible item list"
        edit["dependency_evidence"] = []
        edit["new_values"] = [
            {
                "value": "one click",
                "instruction_evidence": "one-click reset",
                "rationale": "A direct reset is the simplest recovery interaction for this module.",
            }
        ]
    payload["edits"][2]["dependency_evidence"] = [
        {
            "producer_edit": "q1",
            "consumed_state": "saved_items",
            "instruction_evidence": "saved items and active filter",
            "reverse_failure": (
                "Without saved_items, the combined filtered collection cannot be displayed."
            ),
        },
        {
            "producer_edit": "q2",
            "consumed_state": "active_filter",
            "instruction_evidence": "saved items and active filter",
            "reverse_failure": (
                "Without active_filter, the combined filtered collection cannot be displayed."
            ),
        },
    ]

    normalized = validate_edit_sequence(
        payload,
        seed_id="seed-a",
        donor_ids=set(),
        edit_count=None,
        host_evidence_corpus="The visible item list contains stable local records.",
    )

    assert len(normalized["edits"][2]["dependency_evidence"]) == 2

    paraphrased = json.loads(json.dumps(payload))
    paraphrased['edits'][0]['source_claims'][0]['claim'] = 'An enumerable collection is available.'
    reviewed = validate_edit_sequence(paraphrased, seed_id='seed-a', donor_ids=set(),
        edit_count=None, host_evidence_corpus='The visible item list contains stable local records.')
    assert any('check semantic support' in note for note in reviewed['review_notes'])

    broken = json.loads(json.dumps(payload))
    broken["edits"][2]["dependency_evidence"][0]["instruction_evidence"] = (
        "a phrase not present in the instruction"
    )
    with pytest.raises(ValueError, match="not an exact instruction phrase"):
        validate_edit_sequence(
            broken,
            seed_id="seed-a",
            donor_ids=set(),
            edit_count=None,
            host_evidence_corpus="The visible item list contains stable local records.",
        )

    hidden_dependency = json.loads(json.dumps(payload))
    hidden_dependency["edits"][3]["instruction"] = hidden_dependency["edits"][3][
        "instruction"
    ].replace("visible item list", "saved items list")
    flagged = validate_edit_sequence(
            hidden_dependency,
            seed_id="seed-a",
            donor_ids=set(),
            edit_count=None,
            host_evidence_corpus="The visible item list contains stable local records.",
        )
    assert any('check actual state consumption' in note for note in flagged['review_notes'])


def test_browser_derived_host_facts_records_repeated_count_and_year_range() -> None:
    observation = {
        "baseline": {"record_groups": []},
        "exploration_paths": [
            {
                "after": {
                    "record_groups": [
                        {
                            "item_tag": "article",
                            "item_class_signature": "artifact-card",
                            "item_count": 3,
                            "records": [
                                {"text": "Clock\nCirca 1892"},
                                {"text": "Letter\nCirca 1863"},
                                {"text": "Photo\nCirca 1924"},
                            ],
                        }
                    ]
                }
            }
        ],
    }

    assert browser_derived_host_facts(observation) == [
        {
            "item_tag": "article",
            "item_role": None,
            "item_class_signature": "artifact-card",
            "item_count": 3,
            "observed_four_digit_values": [1863, 1892, 1924],
            "four_digit_min": 1863,
            "four_digit_max": 1924,
            "observed_record_year_values": [1863, 1892, 1924],
            "observed_record_year_min": 1863,
            "observed_record_year_max": 1924,
        }
    ]


def test_validate_edit_sequence_rejects_count_outside_supported_range() -> None:
    with pytest.raises(ValueError, match="edit_count must be from 4 to 12"):
        validate_edit_sequence(
            _valid_sequence(4),
            seed_id="seed-a",
            donor_ids=set(),
            edit_count=3,
        )


def test_validate_edit_sequence_requires_real_state_consumption() -> None:
    payload = _valid_sequence()
    payload["edits"][2]["requires"][0]["state"] = "invented_state"
    with pytest.raises(ValueError, match="does not exactly match"):
        validate_edit_sequence(payload, seed_id="seed-a", donor_ids=set())


def test_validate_edit_sequence_canonicalizes_only_explicit_source_suffix() -> None:
    payload = _valid_sequence()
    payload["edits"][2]["requires"][0]["state"] = "saved_items from q1"

    normalized = validate_edit_sequence(payload, seed_id="seed-a", donor_ids=set())
    requirement = normalized["edits"][2]["requires"][0]

    assert requirement["state"] == "saved_items"
    assert requirement["provider_state"] == "saved_items from q1"
    assert requirement["state_match_status"] == "canonicalized_explicit_source_suffix"


def test_validate_edit_sequence_rejects_ambiguous_dependency_state() -> None:
    payload = _valid_sequence()
    payload["edits"][0]["produces"].append(
        {
            "state": "saved_item_metadata",
            "value_shape": "object keyed by item id",
            "scope": "page",
            "persistence": "memory",
            "observable": "saved item metadata panel",
        }
    )
    payload["edits"][2]["requires"][0]["state"] = "invented_state"
    with pytest.raises(ValueError, match="does not exactly match"):
        validate_edit_sequence(payload, seed_id="seed-a", donor_ids=set())


def test_validate_edit_sequence_rejects_duplicate_requirements() -> None:
    payload = _valid_sequence()
    payload["edits"][2]["requires"].append(dict(payload["edits"][2]["requires"][0]))

    with pytest.raises(ValueError, match="duplicate required states"):
        validate_edit_sequence(payload, seed_id="seed-a", donor_ids=set())


def test_validate_edit_sequence_rejects_hidden_donor_code_leakage() -> None:
    payload = _valid_sequence()
    payload["edits"][0]["origin"] = "verified_donor_adaptation"
    payload["edits"][0]["donor_capability_id"] = "saved-filter-card"
    payload["edits"][0]["instruction"] = (
        "Implement a saved-filter management module beside the existing workspace search controls. "
        "Let users capture the current filter under a visible name, restore it later, and remove saved entries "
        "without changing the underlying item data. Implement persistence with "
        "state.savedViews.push(currentFilterSnapshot) so restored filters remain visible after a reload and "
        "update the result count immediately. Show duplicate-name feedback, an empty saved-views state, and a "
        "confirmation after deletion. Keep search keyboard accessible, preserve the active item ordering, and "
        "reflow the saved-filter panel below the search bar on narrow screens."
    )
    planner_cards = [
        {
            "capability_id": "saved-filter-card",
            "requires": ["stable local items"],
            "donor_snippets": [
                {
                    "snippet_id": "saved-filter-card__snippet_1",
                    "path": "app.js",
                    "code": "state.savedViews.push(currentFilterSnapshot); renderSavedViews();",
                }
            ],
        }
    ]
    _attach_card_assessments(payload, planner_cards, {"saved-filter-card"})

    with pytest.raises(ValueError, match="hidden donor"):
        validate_edit_sequence(
            payload,
            seed_id="seed-a",
            donor_ids={"saved-filter-card"},
            planner_cards=planner_cards,
        )


def test_validate_edit_sequence_allows_public_web_api_names_in_hidden_slices() -> None:
    payload = _valid_sequence()
    payload["edits"][0]["origin"] = "verified_donor_adaptation"
    payload["edits"][0]["donor_capability_id"] = "saved-filter-card"
    payload["edits"][1]["origin"] = "verified_donor_adaptation"
    payload["edits"][1]["donor_capability_id"] = "second-card"
    payload["edits"][0]["instruction"] = payload["edits"][0]["instruction"].replace(
        "collection count update immediately.",
        "collection count update immediately and store the selection in localStorage.",
    )
    planner_cards = [
        {
            "capability_id": "saved-filter-card",
            "requires": ["stable local items"],
            "donor_snippets": [
                {
                    "snippet_id": "saved-filter-card__snippet_1",
                    "path": "app.js",
                    "code": "localStorage.setItem('saved', JSON.stringify(savedViews));",
                }
            ],
        },
        {
            "capability_id": "second-card",
            "requires": ["visible item workspace"],
            "donor_snippets": [],
        },
    ]
    _attach_card_assessments(
        payload, planner_cards, {"saved-filter-card", "second-card"}
    )

    normalized = validate_edit_sequence(
        payload,
        seed_id="seed-a",
        donor_ids={"saved-filter-card", "second-card"},
        planner_cards=planner_cards,
    )

    assert "localStorage" in normalized["edits"][0]["instruction"]


def test_normalize_repeated_openings_changes_wording_not_requirements() -> None:
    payload = _valid_sequence()
    for edit in payload["edits"]:
        edit["instruction"] = "Add" + edit["instruction"].split(" ", 1)[1]
    before_dependencies = [edit["depends_on"] for edit in payload["edits"]]

    normalized = normalize_repeated_instruction_openings(payload)

    openings = [edit["instruction"].split(" ", 1)[0] for edit in normalized["edits"]]
    assert max(openings.count(opening) for opening in set(openings)) <= 2
    assert [edit["depends_on"] for edit in normalized["edits"]] == before_dependencies
    assert all(
        before["instruction"].split(" ", 1)[1]
        == after["instruction"].split(" ", 1)[1]
        for before, after in zip(payload["edits"], normalized["edits"], strict=True)
    )


def test_validate_edit_sequence_flags_short_instruction_for_semantic_review() -> None:
    payload = _valid_sequence()
    payload["edits"][0]["instruction"] = (
        "Add a clear button beside the search input. Clicking it restores every visible item."
    )

    result = validate_edit_sequence(payload, seed_id="seed-a", donor_ids=set())
    assert any('length outside suggested range' in note for note in result['review_notes'])


def test_validate_edit_sequence_flags_single_sentence_for_semantic_review() -> None:
    payload = _valid_sequence()
    payload["edits"][0]["instruction"] = (
        "Implement a complete filtering module with visible results, a result count, an empty state, a reset "
        "control, keyboard operation, accessible status feedback, responsive placement, preserved item ordering, "
        "persistent query restoration, clear selected styling, deterministic local data, immediate updates, "
        "helpful error text, stable focus behavior, mobile reflow, desktop alignment, readable labels, reversible "
        "actions, and protection for every unrelated item action while keeping the entire user journey inside "
        "one deliberately long sentence that should not qualify as a complete multi-sentence instruction overall."
    )

    result = validate_edit_sequence(payload, seed_id="seed-a", donor_ids=set())
    assert any('sentence count outside suggested range' in note for note in result['review_notes'])


def test_validate_edit_sequence_rejects_one_repeated_opening() -> None:
    payload = _valid_sequence()
    for edit in payload["edits"]:
        edit["instruction"] = re.sub(r"^[A-Za-z]+", "Implement", edit["instruction"])

    with pytest.raises(ValueError, match="same instruction opening"):
        validate_edit_sequence(payload, seed_id="seed-a", donor_ids=set())


def test_validate_edit_sequence_requires_distinct_compatible_retrieved_cards() -> None:
    planner_cards = [
        {
            "capability_id": "card-a",
            "requires": ["stable local items"],
            "source_slices": [],
        },
        {
            "capability_id": "card-b",
            "requires": ["visible item workspace"],
            "source_slices": [],
        },
    ]
    missing = _valid_sequence()
    _attach_card_assessments(missing, planner_cards, {"card-a", "card-b"})
    with pytest.raises(ValueError, match="2 distinct compatible"):
        validate_edit_sequence(
            missing,
            seed_id="seed-a",
            donor_ids={"card-a", "card-b"},
            planner_cards=planner_cards,
        )

    payload = _valid_sequence()
    for index, card_id in enumerate(("card-a", "card-b")):
        payload["edits"][index]["origin"] = "verified_donor_adaptation"
        payload["edits"][index]["donor_capability_id"] = card_id
    _attach_card_assessments(payload, planner_cards, {"card-a", "card-b"})
    normalized = validate_edit_sequence(
        payload,
        seed_id="seed-a",
        donor_ids={"card-a", "card-b"},
        planner_cards=planner_cards,
    )

    assert normalized["donor_edit_count"] == 2
    assert normalized["compatible_card_count"] == 2


def test_validate_edit_sequence_does_not_force_incompatible_retrieved_cards() -> None:
    planner_cards = [
        {
            "capability_id": "per-record-filter",
            "requires": ["a category field on every repeated record"],
            "source_slices": [],
        }
    ]
    payload = _valid_sequence()
    _attach_card_assessments(payload, planner_cards, set())

    normalized = validate_edit_sequence(
        payload,
        seed_id="seed-a",
        donor_ids={"per-record-filter"},
        planner_cards=planner_cards,
    )

    assert normalized["compatible_card_count"] == 0
    assert normalized["donor_edit_count"] == 0

    payload["edits"][0]["origin"] = "verified_donor_adaptation"
    payload["edits"][0]["donor_capability_id"] = "per-record-filter"
    with pytest.raises(ValueError, match="assessed as incompatible"):
        validate_edit_sequence(
            payload,
            seed_id="seed-a",
            donor_ids={"per-record-filter"},
            planner_cards=planner_cards,
        )


def test_validate_edit_sequence_records_forward_and_reverse_order_checks() -> None:
    normalized = validate_edit_sequence(
        _valid_sequence(), seed_id="seed-a", donor_ids=set()
    )

    assert normalized["order_diagnostics"] == [
        {
            "producer_edit": "q1",
            "consumer_edit": "q3",
            "forward_order": "q1->q3",
            "forward_status": "valid_by_declared_state_flow",
            "reverse_order": "q3->q1",
            "reverse_status": "invalid_before_producer",
            "consumed_states": ["saved_items"],
            "evidence_scope": "instruction_plan_only",
        },
        {
            "producer_edit": "q2",
            "consumer_edit": "q3",
            "forward_order": "q2->q3",
            "forward_status": "valid_by_declared_state_flow",
            "reverse_order": "q3->q2",
            "reverse_status": "invalid_before_producer",
            "consumed_states": ["active_filter"],
            "evidence_scope": "instruction_plan_only",
        },
        {
            "producer_edit": "q3",
            "consumer_edit": "q5",
            "forward_order": "q3->q5",
            "forward_status": "valid_by_declared_state_flow",
            "reverse_order": "q5->q3",
            "reverse_status": "invalid_before_producer",
            "consumed_states": ["filtered_saved_items"],
            "evidence_scope": "instruction_plan_only",
        },
        {
            "producer_edit": "q4",
            "consumer_edit": "q8",
            "forward_order": "q4->q8",
            "forward_status": "valid_by_declared_state_flow",
            "reverse_order": "q8->q4",
            "reverse_status": "invalid_before_producer",
            "consumed_states": ["notes"],
            "evidence_scope": "instruction_plan_only",
        },
    ]


def test_current_runner_exports_after_deterministic_checks_without_audit_call(
    tmp_path: Path,
) -> None:
    sequence = validate_edit_sequence(
        _valid_sequence(), seed_id="seed-a", donor_ids=set()
    )
    sequence["retrieval"] = {
        "top_k": 4,
        "retrieved_capability_ids": ["card-a", "card-b", "card-c", "card-d"],
    }
    observation = {
        "status": "ok",
        "baseline": {
            "state_sha256": "base",
            "interactive": [],
            "structures": [],
            "html": "<main>Items</main>",
            "aria_snapshot": "- main",
            "visible_text": "Items",
        },
        "exploration_paths": [],
        "remote_requests": [],
        "console_errors": [],
        "page_errors": [],
    }
    seed = {
        "seed_id": "seed-a",
        "dataset": "0805",
        "project_path": "/seed-a",
    }
    output = tmp_path / "edit_queries.jsonl"

    export_queries(
        seed=seed,
        observation=observation,
        sequence=sequence,
        output_path=output,
    )

    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 10
    assert all(row["status"] == "ok" for row in rows)
    assert all(row["instruction_validation"]["independent_llm_audit"] is False for row in rows)
    assert all("quality" not in row for row in rows)

    sequence['instruction_review'] = _accepted_quality_audit()
    audited_output = tmp_path/'audited.jsonl'
    export_queries(seed=seed, observation=observation, sequence=sequence, output_path=audited_output)
    audited = [json.loads(line) for line in audited_output.read_text().splitlines()]
    assert all(row['instruction_validation']['independent_llm_audit'] for row in audited)
    assert all(row['target_status'] == 'not_generated' for row in audited)
    sequence['instruction_review']['sequence_decision'] = 'reject'
    with pytest.raises(ValueError, match='semantically rejected'):
        export_queries(seed=seed, observation=observation, sequence=sequence, output_path=tmp_path/'rejected.jsonl')


def test_complete_task_can_reference_multiple_known_donors():
    payload = _valid_sequence()
    payload['edits'][0].update(origin='retrieved_card_adaptation', donor_capability_id=['card-a','card-b'])
    result = validate_edit_sequence(payload, seed_id='seed-a', donor_ids={'card-a','card-b'})
    assert result['edits'][0]['donor_capability_id'] == 'card-a'
    assert result['edits'][0]['donor_capability_ids'] == ['card-a','card-b']
    with pytest.raises(ValueError, match='unknown donor'):
        validate_edit_sequence(payload, seed_id='seed-a', donor_ids={'card-a'})


def test_validate_edit_sequence_normalizes_provider_shape_variants() -> None:
    payload = _valid_sequence()
    payload["edits"][0]["origin"] = "verified_donor"
    payload["edits"][0]["donor_capability_id"] = "persistent_named_filter_views"
    payload["edits"][0]["preserve"] = "Keep current search behavior."
    payload["edits"][0]["acceptance"] = "The visible result changes after the action."
    payload["edits"][0]["dependency_reason"] = ""
    payload["edits"][0]["requires"][0]["source"] = "host"
    payload["edits"][1]["depends_on"] = None
    payload["edits"][2]["depends_on"] = "q1,q2"
    payload["edits"][2]["requires"][0]["source"] = "q1 output"
    payload["edits"][2]["requires"][1]["source"] = "q2 output"
    normalized = validate_edit_sequence(
        payload,
        seed_id="seed-a",
        donor_ids={"persistent_named_filter_views"},
    )
    assert normalized["edits"][0]["origin"] == "verified_donor_adaptation"
    assert normalized["edits"][0]["preserve"] == ["Keep current search behavior."]
    assert normalized["edits"][0]["dependency_reason"].startswith("Independent")
    assert normalized["edits"][0]["requires"][0]["source"] == "seed"
    assert normalized["edits"][1]["depends_on"] == []
    assert normalized["edits"][2]["depends_on"] == ["q1", "q2"]


def test_load_json_response_repairs_only_unescaped_inner_quotes(tmp_path: Path) -> None:
    path = tmp_path / "response.txt"
    path.write_text(
        '{"decision":"reject","evidence":"The <article class="post"> is sequential."}',
        encoding="utf-8",
    )
    assert load_json_response(path)["evidence"] == (
        'The <article class="post"> is sequential.'
    )
