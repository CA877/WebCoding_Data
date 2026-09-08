from __future__ import annotations

import json
from pathlib import Path

from src.orchestration.atomic_edit_plan import write_atomic_edit_plan
from src.orchestration.edit_risk_tests import materialize_edit_risk_tests
from src.orchestration.edit_task_contract import prepare_edit_task_contract
from src.orchestration.hidden_oracle_checks import (
    read_hidden_oracle_checks,
    write_hidden_oracle_checks,
)
from src.orchestration.webcompass_protocol import REPAIR_TYPES


INSTRUCTION = (
    "Add a responsive dark-theme modal with a form, image preview, and Save button "
    "on both the dashboard and settings pages."
)


def _plan() -> dict:
    checks = []
    for index, route in enumerate(("/", "/settings.html"), start=1):
        checks.append({
            "id": f"UI-MODAL-{index}",
            "task": "Open and inspect the responsive modal form.",
            "expected_result": "The dialog is usable without changing the surrounding layout.",
            "critical": True,
            "category": "responsive interaction layout",
            "requirement_id": "REQ-MODAL",
            "impact_tags": ["modal", "form", "dark-theme", f"route:{route}"],
            "route": route,
            "fixtures": [],
            "actions": [
                {"action": "set_viewport", "width": 390, "height": 844},
                {"action": "click", "selector": "[data-testid='open-modal']"},
                {"action": "assert_visible", "selector": "[data-testid='edit-modal']"},
            ],
        })
    return {
        "schema_version": "atomic-edit-plan-v1",
        "title": "Add responsive modal",
        "goal": INSTRUCTION,
        "source_anchors": ["dashboard", "settings"],
        "deliverables": ["A responsive modal form with image preview."],
        "exit_criteria": ["The modal is operable on both routes."],
        "requirement_changes": [{
            "requirement_id": "REQ-MODAL",
            "relation": "add",
            "prior_requirement_ids": [],
            "rationale": INSTRUCTION,
        }],
        "impact_tags": ["modal", "responsive", "form", "dark-theme"],
        "unresolved_conflicts": [],
        "visual_evidence": "required",
        "visual_evidence_reason": "The modal changes responsive layout and theme styling.",
        "checks": checks,
    }


def _prepared(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text(
        "<main><button data-testid='open-modal'>Open</button></main>", encoding="utf-8"
    )
    (frontend / "settings.html").write_text(
        "<main><form><button data-testid='open-modal'>Open</button></form></main>",
        encoding="utf-8",
    )
    prepare_edit_task_contract(
        tmp_path, requested_target_routes=["/", "/settings.html"]
    )
    write_atomic_edit_plan(
        tmp_path / ".harness", _plan(), instruction_delta=INSTRUCTION
    )


def test_source_edit_risk_analysis_selects_relevant_subset_and_covers_routes(
    tmp_path: Path,
):
    _prepared(tmp_path)

    profile = materialize_edit_risk_tests(
        workdir=tmp_path, instruction_delta=INSTRUCTION, max_checks=6
    )
    checks = read_hidden_oracle_checks(tmp_path / ".harness")

    assert 2 <= len(checks) <= 6
    assert {check["route"] for check in checks} == {"/", "/settings.html"}
    assert {check["repair_type"] for check in checks} < REPAIR_TYPES
    assert "Loss of Interactivity" in {check["repair_type"] for check in checks}
    assert all(check["origin"] == "source_edit_risk_analysis" for check in checks)
    assert all(
        check["actions"][-1]["action"] == "assert_webcompass_risk"
        for check in checks
    )
    assert len(profile["risk_decisions"]) == 2 * len(REPAIR_TYPES)
    assert sum(item["selected"] for item in profile["risk_decisions"]) == len(checks)


def test_source_edit_risk_analysis_preserves_user_hidden_oracle(tmp_path: Path):
    _prepared(tmp_path)
    write_hidden_oracle_checks(
        tmp_path / ".harness",
        [{
            "id": "USER-ORACLE",
            "route": "/",
            "actions": [{"action": "assert_hash", "value": ""}],
        }],
        target_routes=["/", "/settings.html"],
    )

    materialize_edit_risk_tests(
        workdir=tmp_path, instruction_delta=INSTRUCTION, max_checks=4
    )
    checks = read_hidden_oracle_checks(tmp_path / ".harness")

    assert checks[0]["id"] == "USER-ORACLE"
    assert len(checks) == 5


def test_risk_profile_contains_no_candidate_or_target_implementation(tmp_path: Path):
    _prepared(tmp_path)

    profile = materialize_edit_risk_tests(
        workdir=tmp_path, instruction_delta=INSTRUCTION
    )
    raw = json.dumps(profile, ensure_ascii=False).casefold()

    assert profile["status"] == "authored_before_build"
    assert profile["baseline_commit"]
    assert "candidate_implementation" not in raw
    assert "target_screenshot" not in raw


def test_default_defect_audit_covers_taxonomy_on_each_target_route(tmp_path: Path):
    _prepared(tmp_path)
    profile = materialize_edit_risk_tests(workdir=tmp_path, instruction_delta="Update this surface")
    checks = read_hidden_oracle_checks(tmp_path / ".harness")
    assert profile["test_policy"] == "webcompass_defects_first"
    for route in ("/", "/settings.html"):
        assert {item["repair_type"] for item in checks if item["route"] == route} == REPAIR_TYPES
    assert len(checks) == 22


def test_multiple_target_states_are_not_collapsed_to_first_route_check(tmp_path: Path):
    _prepared(tmp_path)
    plan = _plan()
    additional = json.loads(json.dumps(plan["checks"][0]))
    additional["id"] = "UI-SECOND-STATE"
    additional["actions"][-1]["selector"] = "[data-testid='second-modal']"
    plan["checks"].append(additional)
    write_atomic_edit_plan(tmp_path / ".harness", plan, instruction_delta=INSTRUCTION)
    materialize_edit_risk_tests(workdir=tmp_path, instruction_delta=INSTRUCTION)
    checks = read_hidden_oracle_checks(tmp_path / ".harness")
    assert any(item["actions"][-1]["selector"] == "[data-testid='second-modal']" for item in checks)
