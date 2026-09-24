import json
from pathlib import Path

from reverse.generate.gt.watch_repair import load_done, load_latest_validations


def test_load_done_can_retry_only_failed_rows(tmp_path: Path) -> None:
    path = tmp_path / "repair.jsonl"
    rows = [
        {"project_id": "accepted", "status": "accepted_without_repair"},
        {"project_id": "repaired", "status": "repaired_by_llm"},
        {"project_id": "failed", "status": "repair_failed"},
        {"project_id": "failed_then_repaired", "status": "repair_failed"},
        {"project_id": "failed_then_repaired", "status": "repaired_by_rules"},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")

    assert load_done(path) == {"accepted", "repaired", "failed", "failed_then_repaired"}
    assert load_done(path, retry_failed=True) == {
        "accepted", "repaired", "failed_then_repaired"
    }


def test_load_latest_validations_prefers_last_project_result(tmp_path: Path) -> None:
    path = tmp_path / "validation.jsonl"
    rows = [
        {"project_id": "a", "status": "validator_error"},
        {"project_id": "b", "status": "accept"},
        {"project_id": "a", "status": "needs_repair"},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    assert load_latest_validations(path) == [
        {"project_id": "a", "status": "needs_repair"},
        {"project_id": "b", "status": "accept"},
    ]
