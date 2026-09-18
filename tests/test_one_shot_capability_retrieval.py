from __future__ import annotations

from pathlib import Path

import pytest

from inspiration_library.one_shot_capability_retrieval import (
    build_seed_retrieval_query,
    compile_donor_snippets,
    compile_source_slices,
    compact_planner_card,
    generate_seed_retrieval_plan,
    generate_seed_retrieval_query,
    retrieve_top_k_cards,
    retrieve_top_k_with_snippets,
    validate_generated_retrieval_plan,
)
from inspiration_library.utils.preflight_linear_edit_query_cache import load_completed_preflight


def _card(
    *,
    capability_id: str,
    source_project: Path,
    evidence: str,
    embedding: list[float],
) -> dict:
    return {
        "capability_id": capability_id,
        "source_seed_id": f"source-{capability_id}",
        "source_project": str(source_project),
        "name": capability_id,
        "family": "saved_view",
        "summary": "Save one named view and restore it from a visible list.",
        "prerequisites": ["a filterable local collection"],
        "user_actions": ["save the current view", "restore the saved view"],
        "state_reads": ["current filter"],
        "state_writes": ["saved views"],
        "visible_result": "The saved view appears and restores the prior filter.",
        "source_evidence": [{"path": "app.js", "evidence": evidence}],
        "embedding": embedding,
    }


def test_build_seed_retrieval_query_uses_browser_facts_not_full_source() -> None:
    seed = {
        "seed_id": "host-a",
        "dataset": "0805",
        "original_instruction": (
            "GENERIC OUTPUT BOILERPLATE THAT SHOULD NOT DRIVE RETRIEVAL.\n"
            "Web design document:\nBuild a local item browser."
        ),
        "page_type": "sp",
        "files": {"app.js": "SECRET_FULL_HOST_SOURCE"},
    }
    observation = {
        "status": "ok",
        "baseline": {
            "title": "Item browser",
            "visible_text": "Search items Clear filters",
            "aria_snapshot": '- main:\n  - searchbox "Search items"',
            "interactive": [{"tag": "input", "aria_label": "Search items"}],
            "local_storage": {"theme": "light"},
            "session_storage": {},
            "url": "http://127.0.0.1/index.html",
        },
        "exploration_paths": [],
    }

    query = build_seed_retrieval_query(seed=seed, observation=observation)

    assert "Build a local item browser" in query
    assert "GENERIC OUTPUT BOILERPLATE" not in query
    assert "Search items" in query
    assert "SECRET_FULL_HOST_SOURCE" not in query


def test_llm_writes_retrieval_query_from_bounded_host_evidence() -> None:
    class RecordingClient:
        def __init__(self) -> None:
            self.kwargs = None

        def chat_json(self, **kwargs):
            self.kwargs = kwargs
            return {
                "retrieval_query": (
                    "A local item browser presents stable records, a search field, saved-item state, "
                    "and a dedicated saved-items view. Retrieve complete feature modules that naturally "
                    "extend browsing, comparing, organizing, or visually presenting those local records. "
                    "Each module should connect a full user action path to meaningful visible state and "
                    "task-specific feedback, while remaining feasible with the observed local collection."
                )
            }, {}

    seed = {
        "seed_id": "host-a",
        "original_instruction": "Build a local item browser.",
        "page_type": "sp",
        "files": {"app.js": "SECRET_FULL_HOST_SOURCE"},
    }
    observation = {
        "status": "ok",
        "baseline": {
            "title": "Items",
            "url": "http://127.0.0.1/index.html",
            "visible_text": "Browse items",
            "aria_snapshot": "- main",
            "interactive": [],
        },
        "exploration_paths": [],
    }
    client = RecordingClient()

    query = generate_seed_retrieval_query(
        seed=seed,
        observation=observation,
        client=client,
        request_id="retrieval-query-host-a",
    )

    assert "complete feature modules" in query
    assert "Browse items" in client.kwargs["stable_context"]
    assert "SECRET_FULL_HOST_SOURCE" not in client.kwargs["stable_context"]
    assert client.kwargs["max_tokens"] == 1800


def _retrieval_plan_payload() -> dict:
    rows = []
    for index in range(1, 9):
        edit_id = f"q{index}"
        dependencies = {3: ["q1"], 6: ["q2"]}.get(index, [])
        consumed = {3: "visible_saved_items", 6: "selected_record"}.get(index, "")
        rows.append(
            {
                "edit_id": edit_id,
                "title": f"Distinct module {index}",
                "host_region": f"Host region {index}",
                "goal": (
                    "Create a visible saved items collection for the Host workflow."
                    if index == 1
                    else "Let the user select one record for a focused Host workflow."
                    if index == 2
                    else f"Complete a distinct module {index} user workflow for the Host region."
                    if not dependencies
                    else f"Use {consumed} to complete a distinct module {index} downstream user workflow."
                ),
                "produces_state": (
                    "visible_saved_items"
                    if index == 1
                    else "selected_record"
                    if index == 2
                    else f"module_{index}_result"
                ),
                "host_evidence_quote": "Browse items",
                "source_gap": "The Host does not yet provide this complete user workflow.",
                "depends_on": dependencies,
                "consumes_state": consumed,
                "reverse_failure": (
                    f"Without {consumed}, this downstream visible result cannot be produced."
                    if dependencies
                    else ""
                ),
            }
        )
    return {
        "retrieval_query": (
            "A local item browser presents stable records and visible browsing controls. Retrieve complete "
            "feature modules that extend how users discover, inspect, organize, compare, and present those "
            "records. Each module should connect a concrete user action to a visible product result while "
            "remaining feasible with the observed local collection and page regions."
        ),
        "dependency_plan": ["q3", "q6"],
        "module_plan": rows,
    }


def test_llm_retrieval_call_freezes_grounded_module_plan() -> None:
    class RecordingClient:
        def __init__(self) -> None:
            self.kwargs = None

        def chat_json(self, **kwargs):
            self.kwargs = kwargs
            return _retrieval_plan_payload(), {}

    seed = {
        "seed_id": "host-a",
        "original_instruction": "Build a local item browser.",
        "page_type": "sp",
    }
    observation = {
        "status": "ok",
        "baseline": {
            "title": "Items",
            "url": "http://127.0.0.1/index.html",
            "visible_text": "Browse items",
            "aria_snapshot": "- main",
            "interactive": [],
        },
        "exploration_paths": [],
    }
    client = RecordingClient()

    plan = generate_seed_retrieval_plan(
        seed=seed,
        observation=observation,
        client=client,
        request_id="retrieval-plan-host-a",
    )

    assert plan["dependency_plan"] == ["q3", "q6"]
    assert plan["module_plan"][2]["consumes_state"] == "visible_saved_items"
    assert client.kwargs["max_tokens"] == 4000


def test_retrieval_plan_rejects_a_dependency_that_does_not_copy_state() -> None:
    payload = _retrieval_plan_payload()
    payload["module_plan"][2]["consumes_state"] = "some_other_state"

    with pytest.raises(ValueError, match="must exactly copy"):
        validate_generated_retrieval_plan(
            payload, host_evidence_corpus="Browse items"
        )


def test_retrieval_plan_rejects_an_output_state_absent_from_its_goal() -> None:
    payload = _retrieval_plan_payload()
    payload["module_plan"][3]["produces_state"] = "saved_filter_selection"

    with pytest.raises(ValueError, match="does not describe its own produces_state"):
        validate_generated_retrieval_plan(
            payload, host_evidence_corpus="Browse items"
        )


def test_retrieval_plan_rejects_weak_discovery_dependency_and_unobserved_submission() -> None:
    weak = _retrieval_plan_payload()
    weak["module_plan"][2].update(
        {
            "title": "Visible item comparison",
            "goal": "Show a comparison view of the currently visible saved items side by side.",
            "produces_state": "comparison_view",
            "consumes_state": "visible_saved_items",
            "reverse_failure": (
                "Without visible_saved_items, the comparison has no filtered records to display."
            ),
        }
    )
    with pytest.raises(ValueError, match="weak dependency"):
        validate_generated_retrieval_plan(weak, host_evidence_corpus="Browse items")

    external = _retrieval_plan_payload()
    external["module_plan"][3].update(
        {
            "title": "Record inquiry",
            "goal": "Submit an inquiry request about a record to the archive team.",
            "produces_state": "inquiry_request",
        }
    )
    with pytest.raises(ValueError, match="external submission"):
        validate_generated_retrieval_plan(external, host_evidence_corpus="Browse items")

    feedback = _retrieval_plan_payload()
    feedback["module_plan"][3].update(
        {
            "title": "Saved item confirmation message",
            "goal": "Show a confirmation message after an item is saved.",
            "produces_state": "saved_confirmation_message",
        }
    )
    with pytest.raises(ValueError, match="micro-Edit"):
        validate_generated_retrieval_plan(feedback, host_evidence_corpus="Browse items")


def test_build_seed_retrieval_query_includes_deep_browser_states() -> None:
    seed = {
        "seed_id": "host-a",
        "original_instruction": "Build a local item browser.",
        "page_type": "sp",
    }
    observation = {
        "status": "ok",
        "baseline": {
            "title": "Items",
            "url": "http://127.0.0.1/index.html",
            "visible_text": "Browse items",
            "aria_snapshot": "- main",
            "interactive": [],
        },
        "exploration_paths": [
            {
                "id": "open_saved",
                "purpose": "Reveal saved-item behavior",
                "status": "ok",
                "steps": [
                    {
                        "action": {"action": "click", "selector": "#saved"},
                        "state": {
                            "url": "http://127.0.0.1/index.html#saved",
                            "visible_text": "Saved items Empty list",
                            "aria_snapshot": '- region "Saved items"',
                            "interactive": [
                                {"tag": "button", "text": "Clear saved items"}
                            ],
                            "local_storage": {"saved": "[]"},
                            "session_storage": {},
                        },
                    }
                ],
                "after": {
                    "url": "http://127.0.0.1/index.html#saved",
                    "visible_text": "Saved items Empty list",
                    "aria_snapshot": '- region "Saved items"',
                    "interactive": [{"tag": "button", "text": "Clear saved items"}],
                    "local_storage": {"saved": "[]"},
                    "session_storage": {},
                },
            }
        ],
    }

    query = build_seed_retrieval_query(seed=seed, observation=observation)

    assert "Reveal saved-item behavior" in query
    assert "Clear saved items" in query
    assert "Saved items Empty list" in query


def test_build_seed_retrieval_query_is_bounded_when_states_repeat_large_pages() -> None:
    seed = {
        "seed_id": "host-large",
        "original_instruction": "Build a local collection workspace.",
        "page_type": "sp",
    }
    baseline = {
        "state_sha256": "base",
        "title": "Collection",
        "url": "http://127.0.0.1/index.html",
        "html": "<main>" + "same markup " * 10000 + "</main>",
        "visible_text": "Collection\nSearch",
        "aria_snapshot": '- main\n  - searchbox "Search"',
        "interactive": [{"selector": "#search", "tag": "input", "text": "Search"}],
        "local_storage": {},
        "session_storage": {},
    }
    steps = []
    prior = baseline
    for index in range(8):
        current = {
            **prior,
            "state_sha256": f"state-{index}",
            "visible_text": prior["visible_text"] + f"\nState result {index}",
        }
        steps.append(
            {
                "action": {"action": "click", "selector": "#search"},
                "state": current,
            }
        )
        prior = current
    observation = {
        "status": "ok",
        "baseline": baseline,
        "exploration_paths": [
            {"id": "many_states", "purpose": "Reveal states", "status": "ok", "steps": steps}
        ],
    }

    query = build_seed_retrieval_query(seed=seed, observation=observation)

    assert "State result 7" in query
    assert "same markup" not in query
    assert len(query) < 16000


def test_build_seed_retrieval_query_has_a_hard_budget_for_many_rich_states() -> None:
    seed = {
        "seed_id": "host-rich",
        "original_instruction": "Build a local operations workspace. " * 1000,
        "page_type": "sp",
    }
    baseline = {
        "state_sha256": "base",
        "title": "Operations",
        "url": "http://127.0.0.1/index.html",
        "visible_text": "Operations\nSearch\n" + "baseline detail " * 1000,
        "aria_snapshot": '- main\n  - searchbox "Search"\n' + "AX detail\n" * 1000,
        "interactive": [
            {
                "selector": f"#control-{index}",
                "tag": "button",
                "text": f"Control {index} " + "description " * 100,
            }
            for index in range(100)
        ],
        "style_samples": [
            {"selector": f"#surface-{index}", "color": "rgb(1, 2, 3) " * 100}
            for index in range(50)
        ],
        "local_storage": {},
        "session_storage": {},
    }
    paths = []
    for index in range(30):
        state = {
            **baseline,
            "state_sha256": f"state-{index}",
            "visible_text": baseline["visible_text"] + f"\nUnique result {index}",
            "style_samples": baseline["style_samples"]
            + [{"selector": f"#changed-{index}", "color": "blue " * 1000}],
        }
        paths.append(
            {
                "id": f"path-{index}",
                "purpose": f"Reveal result {index}",
                "status": "ok",
                "steps": [
                    {
                        "action": {"action": "click", "selector": f"#control-{index}"},
                        "state": state,
                    }
                ],
            }
        )
    observation = {"status": "ok", "baseline": baseline, "exploration_paths": paths}

    query = build_seed_retrieval_query(seed=seed, observation=observation)

    assert "Reveal result 0" in query
    assert "Reveal result 29" in query
    assert "Control 99" in query
    assert len(query) <= 24000


def test_compact_planner_card_keeps_only_fields_used_after_retrieval() -> None:
    raw = {
        "capability_id": "saved-filter",
        "source_seed_id": "donor-a",
        "source_project": "/private/donor-a",
        "name": "Saved filters",
        "family": "persistence",
        "summary": "Save and restore a named filter configuration.",
        "prerequisites": ["a filterable collection"],
        "user_actions": ["save the current filter", "restore one saved filter"],
        "state_reads": ["active filter"],
        "state_writes": ["saved filter configurations"],
        "visible_result": "The saved filter appears and restores the result list.",
        "future_uses": ["export a restored result list"],
        "verification_status": "candidate",
        "browser_checks": [{"id": "unused"}],
        "source_evidence": [{"path": "app.js", "evidence": "summary only"}],
    }
    source_slices = [
        {
            "slice_id": "saved-filter__slice_1",
            "path": "src/FilterPanel.vue",
            "start_line": 10,
            "end_line": 18,
            "language": "vue",
            "sha256": "a" * 64,
            "content": "const saved = ref([])",
        }
    ]

    compact = compact_planner_card(raw, source_slices=source_slices)

    assert set(compact) == {
        "capability_id",
        "change_type",
        "summary",
        "requires",
        "user_actions",
        "produces",
        "visible_result",
        "future_uses",
        "source_slices",
    }
    assert compact["change_type"] == "persistence"
    assert compact["requires"] == ["a filterable collection", "active filter"]
    assert compact["produces"] == ["saved filter configurations"]
    assert "source_project" not in compact
    assert "source_evidence" not in compact


def test_compile_donor_snippets_resolves_ellipsized_evidence_to_exact_lines(
    tmp_path: Path,
) -> None:
    donor = tmp_path / "donor"
    donor.mkdir()
    source = """const state = { filters: {}, saved: [] };
function saveView(name) {
  const snapshot = { name, filters: { ...state.filters } };
  state.saved.push(snapshot);
  renderSavedViews();
}
"""
    (donor / "app.js").write_text(source, encoding="utf-8")
    card = _card(
        capability_id="saved-filter",
        source_project=donor,
        evidence="saveView(name) { ... state.saved.push(snapshot); ... renderSavedViews(); }",
        embedding=[1.0, 0.0],
    )

    snippets = compile_donor_snippets(card, context_lines=1)

    assert snippets
    assert snippets[0]["path"] == "app.js"
    assert snippets[0]["start_line"] <= 4 <= snippets[0]["end_line"]
    assert "state.saved.push(snapshot);" in snippets[0]["content"]
    assert len(snippets[0]["sha256"]) == 64
    assert snippets[0]["content"] == "\n".join(
        source.splitlines()[
            snippets[0]["start_line"] - 1 : snippets[0]["end_line"]
        ]
    )


@pytest.mark.parametrize(
    ("filename", "language"),
    [
        ("src/Panel.vue", "vue"),
        ("src/Panel.tsx", "typescript"),
        ("src/panel.scss", "scss"),
        ("src/Panel.svelte", "svelte"),
        ("src/Panel.astro", "astro"),
    ],
)
def test_compile_source_slices_is_framework_independent(
    tmp_path: Path, filename: str, language: str
) -> None:
    donor = tmp_path / "donor"
    path = donor / filename
    path.parent.mkdir(parents=True)
    path.write_text("before\nconst selectedIds = new Set();\nafter\n", encoding="utf-8")
    card = _card(
        capability_id="selection",
        source_project=donor,
        evidence="const selectedIds = new Set();",
        embedding=[1.0, 0.0],
    )
    card["source_evidence"] = [
        {"path": filename, "evidence": "const selectedIds = new Set();"}
    ]

    slices = compile_donor_snippets(card, context_lines=0)

    assert slices[0]["language"] == language
    assert slices[0]["content"] == "const selectedIds = new Set();"
    assert "code" not in slices[0]


def test_compile_source_slices_can_use_browser_derived_exact_anchors(
    tmp_path: Path,
) -> None:
    donor = tmp_path / "donor"
    component = donor / "src" / "ComparePanel.tsx"
    component.parent.mkdir(parents=True)
    component.write_text(
        "export function ComparePanel() {\n"
        "  const label = 'View differences';\n"
        "  return <button aria-label={label}>View differences</button>;\n"
        "}\n",
        encoding="utf-8",
    )
    card = {
        **_card(
            capability_id="comparison-threshold",
            source_project=donor,
            evidence="not used",
            embedding=[1.0, 0.0],
        ),
        "source_evidence": [],
        "source_anchors": ["View differences"],
    }

    slices = compile_source_slices(card, context_lines=1)

    assert slices
    assert slices[0]["path"] == "src/ComparePanel.tsx"
    assert slices[0]["locator_method"] == "exact_browser_anchor"
    assert "View differences" in slices[0]["content"]


def test_compile_source_slices_maps_runtime_selector_id_to_source(
    tmp_path: Path,
) -> None:
    donor = tmp_path / "donor"
    donor.mkdir()
    (donor / "app.js").write_text(
        "const value = document.getElementById('material-filter').value;\n",
        encoding="utf-8",
    )
    card = {
        **_card(
            capability_id="material_filter",
            source_project=donor,
            evidence="not used",
            embedding=[1.0, 0.0],
        ),
        "source_evidence": [],
        "source_anchors": ["#material-filter"],
    }

    slices = compile_source_slices(card, context_lines=0)

    assert slices[0]["locator_method"] == "runtime_selector_id"
    assert "material-filter" in slices[0]["content"]


def test_compile_source_slices_maps_observed_layout_to_responsive_rule(
    tmp_path: Path,
) -> None:
    donor = tmp_path / "donor"
    donor.mkdir()
    (donor / "styles.css").write_text(
        "@media (max-width: 768px) {\n  .grid { grid-template-columns: 1fr; }\n}\n",
        encoding="utf-8",
    )
    card = {
        **_card(
            capability_id="seed__responsive_layout",
            source_project=donor,
            evidence="not used",
            embedding=[1.0, 0.0],
        ),
        "change_type": "layout",
        "family": "responsive",
        "source_evidence": [],
        "source_anchors": ["section:nth-of-type(3)"],
    }

    slices = compile_source_slices(card, context_lines=1)

    assert slices[0]["locator_method"] == "layout_source_pattern"
    assert "@media" in slices[0]["content"]


def test_retrieve_top_k_keeps_embedding_order_and_requires_real_snippets(
    tmp_path: Path,
) -> None:
    donor_a = tmp_path / "a"
    donor_b = tmp_path / "b"
    donor_a.mkdir()
    donor_b.mkdir()
    (donor_a / "app.js").write_text(
        "function saveView() { state.saved.push(state.filter); render(); }\n",
        encoding="utf-8",
    )
    (donor_b / "app.js").write_text(
        "function exportRows() { download(state.rows); }\n", encoding="utf-8"
    )
    rows = [
        {
            **_card(
                capability_id="missing-source",
                source_project=tmp_path / "missing",
                evidence="function missing() {}",
                embedding=[1.0, 0.0],
            ),
            "source_seed_id": "source-missing",
        },
        _card(
            capability_id="saved-filter",
            source_project=donor_a,
            evidence="state.saved.push(state.filter);",
            embedding=[0.95, 0.05],
        ),
        _card(
            capability_id="export-rows",
            source_project=donor_b,
            evidence="download(state.rows);",
            embedding=[0.8, 0.2],
        ),
    ]

    retrieved = retrieve_top_k_with_snippets(
        query_vector=[1.0, 0.0],
        embedded_pool=rows,
        host_seed_id="host-a",
        top_k=2,
    )

    assert [row["capability_id"] for row in retrieved] == [
        "saved-filter",
        "export-rows",
    ]
    assert all(row["source_slices"] for row in retrieved)
    assert all("source_evidence" not in row for row in retrieved)
    assert all("source_project" not in row for row in retrieved)
    assert retrieved[0]["similarity"] > retrieved[1]["similarity"]


def test_retrieve_top_k_fails_when_too_few_cards_have_exact_source(tmp_path: Path) -> None:
    rows = [
        _card(
            capability_id="missing-source",
            source_project=tmp_path / "missing",
            evidence="function missing() {}",
            embedding=[1.0, 0.0],
        )
    ]

    with pytest.raises(ValueError, match="compilable source slices"):
        retrieve_top_k_with_snippets(
            query_vector=[1.0, 0.0],
            embedded_pool=rows,
            host_seed_id="host-a",
            top_k=1,
        )


def test_retrieve_top_k_cards_keeps_live_url_card_without_source_slice(
    tmp_path: Path,
) -> None:
    row = _card(
        capability_id="live-calendar-range",
        source_project=tmp_path / "missing",
        evidence="browser-observed date range transition",
        embedding=[1.0, 0.0],
    )
    row.update(
        {
            "source_kind": "live_url",
            "source_url": "https://example.com/calendar",
        }
    )

    selected = retrieve_top_k_cards(
        query_vector=[1.0, 0.0],
        embedded_pool=[row],
        host_seed_id="host-a",
        top_k=1,
    )

    assert selected[0]["capability_id"] == "live-calendar-range"
    assert selected[0]["source_slices"] == []


def test_retrieve_top_k_limits_one_family_before_using_overflow(tmp_path: Path) -> None:
    rows = []
    for index, (family, vector) in enumerate(
        [
            ("navigation", [1.0, 0.0]),
            ("navigation", [0.99, 0.01]),
            ("navigation", [0.98, 0.02]),
            ("persistence", [0.7, 0.3]),
        ]
    ):
        donor = tmp_path / f"donor-{index}"
        donor.mkdir()
        (donor / "app.js").write_text(
            f"function behavior{index}() {{ state.value = {index}; }}\n",
            encoding="utf-8",
        )
        card = _card(
            capability_id=f"card-{index}",
            source_project=donor,
            evidence=f"state.value = {index};",
            embedding=vector,
        )
        card["family"] = family
        rows.append(card)

    retrieved = retrieve_top_k_with_snippets(
        query_vector=[1.0, 0.0],
        embedded_pool=rows,
        host_seed_id="host-a",
        top_k=3,
        max_per_family=2,
    )

    assert {row["capability_id"] for row in retrieved} == {
        "card-0",
        "card-1",
        "card-3",
    }


def test_cache_preflight_resumes_from_successful_paid_artifacts(tmp_path: Path) -> None:
    (tmp_path / "responses").mkdir()
    (tmp_path / "responses" / "linear_cache_1.txt").write_text("{", encoding="utf-8")
    (tmp_path / "responses" / "linear_cache_2.txt").write_text("{", encoding="utf-8")
    (tmp_path / "usage.jsonl").write_text(
        "\n".join(
            [
                '{"request_id":"linear_cache_1","status":"ok","usage":{"prompt_tokens_details":{"cache_creation_input_tokens":7000}}}',
                '{"request_id":"linear_cache_2","status":"ok","usage":{"prompt_tokens_details":{"cached_tokens":7000}}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    completed = load_completed_preflight(tmp_path)

    assert completed is not None
    assert completed[0] == "{"
    assert completed[3]["prompt_tokens_details"]["cached_tokens"] == 7000
