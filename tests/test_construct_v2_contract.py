from collections import Counter
from pathlib import Path
import json
import sys

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from WebCoding_Data.construct.construct_common import (
    apply_search_replace_exact,
    balanced_task_count,
    build_forward_edit_synthesizer,
    validate_patch_round_trip,
)
from WebCoding_Data.construct.v2_records import repair_records
from WebCoding_Data.scripts.pack_construct_v2_release import (
    select_balanced_text_repairs,
    write_provenance,
)
from WebCoding_Data.scripts.audit_construct_v2_release import (
    apply_exact as audit_apply_exact,
    changed_ratio,
    validate_instruction_contract,
    validate_image,
    validate_patch_metadata,
)


def test_balanced_task_counts_are_exactly_uniform() -> None:
    counts = [balanced_task_count(i, 2026, 1, 7) for i in range(700)]
    assert {value: counts.count(value) for value in range(1, 8)} == {
        value: 100 for value in range(1, 8)
    }


def test_exact_patch_rejects_ambiguous_search() -> None:
    code = [{"path": "index.html", "code": "<p>x</p><p>x</p>"}]
    with pytest.raises(ValueError, match="exactly once"):
        apply_search_replace_exact(
            code, [{"path": "index.html", "search": "<p>x</p>", "replace": "<p>y</p>"}]
        )


def test_patch_must_round_trip_on_visible_and_full_code() -> None:
    clean = [{"path": "index.html", "code": "<main>clean</main>"}]
    patches = [{"path": "index.html", "task_type": "Visual", "search": "clean", "replace": "broken"}]
    visible, full = validate_patch_round_trip(clean, clean, patches)
    assert visible == full == [{"path": "index.html", "code": "<main>broken</main>"}]


def test_low_visual_repair_has_text_record_only(tmp_path: Path) -> None:
    project = tmp_path / "case"
    project.mkdir()
    (project / "index.html").write_text("<main>broken</main>", encoding="utf-8")
    record = {
        "instance_id": "case",
        "source_project": str(project),
        "task_type": ["Alignment"],
        "instruction": [{"path": "index.html", "code": "<main>broken</main>"}],
        "label_modified_files": [
            {"path": "index.html", "task_type": "Alignment", "search": "broken", "replace": "clean"}
        ],
        "images": {"src_screenshot": [], "dst_screenshot": []},
        "image_repair_eligible": False,
        "visual_difference": {"max_changed_ratio": 0.004},
        "prompt_tokens": 10,
        "input_contract": {"all_files_included": True},
        "llm_metadata": {},
    }
    text, image = repair_records(record)
    assert text["task"] == "text-repair"
    assert isinstance(text["instruction"], list)
    assert "description" not in text
    assert image is None


def test_text_repair_release_balances_counts_and_keeps_image_pairs() -> None:
    records = []
    paired = set()
    for task_count in range(1, 8):
        for index in range(4 if task_count == 1 else 3):
            instance_id = f"case-{task_count}-{index}"
            records.append({
                "instance_id": instance_id,
                "metadata": {"task_count": task_count},
            })
            if index == 2:
                paired.add(instance_id)

    selected = select_balanced_text_repairs(records, paired)
    selected_ids = {record["instance_id"] for record in selected}
    assert paired <= selected_ids
    assert len(selected) == 21
    assert {
        count: sum(record["metadata"]["task_count"] == count for record in selected)
        for count in range(1, 8)
    } == {count: 3 for count in range(1, 8)}


def test_forward_edit_retries_strict_validation_with_feedback() -> None:
    synthesizer = build_forward_edit_synthesizer(
        "test-key", None, "test-model", max_retries=3
    )
    calls = []

    def fake_generate(*, messages, max_retries):
        calls.append(messages)
        search = "missing" if len(calls) == 1 else "<main>"
        return {
            "description": [{"task_type": "Accordion", "description": "Add an accordion"}],
            "modified_files": [{
                "path": "index.html",
                "task_type": "Accordion",
                "search": search,
                "replace": "<main class=\"accordion\">",
            }],
            "raw_response": "<xml />",
            "llm_metadata": {"model": "test-model"},
        }

    synthesizer._generate = fake_generate
    result = synthesizer.generate_forward_pair(
        {
            "dst_code": [{"path": "index.html", "code": "<main>content</main>"}],
            "full_code": [{"path": "index.html", "code": "<main>content</main>"}],
            "model_context": '<code_context><file path="index.html"><main>content</main></file></code_context>',
            "resources": [],
        },
        ["Accordion"],
    )

    assert len(calls) == 2
    assert "VALIDATION FEEDBACK" in calls[1][1]["content"]
    assert result["llm_metadata"]["validation_attempt"] == 2


def test_release_audit_rejects_non_reversible_exact_patch() -> None:
    with pytest.raises(ValueError, match="search count is 2"):
        audit_apply_exact(
            [{"path": "index.html", "code": "x y"}],
            [{"path": "index.html", "search": "x", "replace": "y"}],
        )


def test_release_audit_enforces_edit_query_task_mapping() -> None:
    valid = {
        "task": "text-editing",
        "instruction": {
            "description": [
                {"task_type": "Accordion", "description": "Add accessible accordion panels."},
                {"task_type": "Dark Mode", "description": "Add a persistent dark-mode toggle."},
            ]
        },
    }
    validate_instruction_contract(valid, ["Accordion", "Dark Mode"])
    valid["instruction"]["description"].reverse()
    validate_instruction_contract(valid, ["Accordion", "Dark Mode"])
    valid["instruction"]["description"][1]["task_type"] = "Carousel"
    with pytest.raises(ValueError, match="map exactly"):
        validate_instruction_contract(valid, ["Accordion", "Dark Mode"])


def test_release_audit_rejects_repair_bug_disclosure() -> None:
    validate_instruction_contract(
        {"task": "image-repair", "instruction": "Repair the provided web project."},
        ["Occlusion"],
    )
    with pytest.raises(ValueError, match="must not disclose"):
        validate_instruction_contract(
            {"task": "image-repair", "instruction": "Fix the injected occlusion bug."},
            ["Occlusion"],
        )


def test_release_audit_enforces_published_patch_counters() -> None:
    record = {
        "response": [
            {"task_type": "Accordion"},
            {"task_type": "Accordion"},
            {"task_type": "Dark Mode"},
        ],
        "metadata": {
            "task_count": 2,
            "patch_count": 3,
            "patch_count_by_task": {"Accordion": 2, "Dark Mode": 1},
        },
    }
    mapping = Counter({"Accordion": 2, "Dark Mode": 1})
    validate_patch_metadata(record, ["Accordion", "Dark Mode"], mapping)
    record["metadata"]["patch_count"] = 2
    with pytest.raises(ValueError, match="patch_count does not match"):
        validate_patch_metadata(record, ["Accordion", "Dark Mode"], mapping)


def test_release_audit_recomputes_pixel_ratio(tmp_path: Path) -> None:
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    Image.new("RGB", (10, 10), "white").save(left)
    changed = Image.new("RGB", (10, 10), "white")
    changed.putpixel((0, 0), (0, 0, 0))
    changed.save(right)
    assert changed_ratio(left, right) == pytest.approx(0.01)


def test_release_audit_rejects_solid_capture_but_accepts_sparse_ui(tmp_path: Path) -> None:
    blank = tmp_path / "blank.png"
    sparse = tmp_path / "sparse.png"
    Image.new("RGB", (400, 400), "white").save(blank)
    canvas = Image.new("RGB", (400, 400), "white")
    for x in range(20, 381):
        canvas.putpixel((x, 20), (80, 80, 80))
    canvas.save(sparse)
    with pytest.raises(ValueError, match="near-uniform"):
        validate_image(blank)
    validate_image(sparse)


def test_release_provenance_is_portable_and_proves_token_gate(tmp_path: Path) -> None:
    production = tmp_path / "production"
    release = tmp_path / "release"
    production.mkdir()
    absolute = "/physical/run/source_projects"
    (production / "eligible_40k_all_files.txt").write_text(
        f"{absolute}/a\n{absolute}/b\n", encoding="utf-8"
    )
    (production / "edit_3000.txt").write_text(f"{absolute}/a\n", encoding="utf-8")
    (production / "repair_candidates_6502.txt").write_text(
        f"{absolute}/a\n{absolute}/b\n", encoding="utf-8"
    )
    (production / "token_gate_audit.jsonl").write_text(
        "\n".join([
            '{"project":"/physical/a","tokens":10,"status":"eligible"}',
            '{"project":"/physical/b","tokens":40000,"status":"eligible"}',
            '{"project":"/physical/c","tokens":40001,"status":"over_token_limit"}',
        ]) + "\n",
        encoding="utf-8",
    )
    (production / "selection_manifest.json").write_text(
        '{"source":"/physical/list","eligible_count":2,"edit_count":1,'
        '"repair_candidate_count":2}',
        encoding="utf-8",
    )

    manifest = write_provenance(production, release)
    assert (release / "provenance/eligible_40k.ids.txt").read_text() == "a\nb\n"
    audit = [json.loads(line) for line in
             (release / "provenance/token_gate_audit.jsonl").read_text().splitlines()]
    assert audit[-1] == {"instance_id": "c", "tokens": 40001, "status": "over_token_limit"}
    assert manifest["token_gate_audit.jsonl"]["count"] == 3
    selection = json.loads((release / "provenance/selection_manifest.json").read_text())
    assert selection["source_input_count"] == 3
    assert selection["maximum_qwen_tokens"] == 40000
