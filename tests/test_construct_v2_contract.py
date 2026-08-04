from pathlib import Path
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
from WebCoding_Data.scripts.pack_construct_v2_release import select_balanced_text_repairs
from WebCoding_Data.scripts.audit_construct_v2_release import (
    apply_exact as audit_apply_exact,
    changed_ratio,
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


def test_release_audit_recomputes_pixel_ratio(tmp_path: Path) -> None:
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    Image.new("RGB", (10, 10), "white").save(left)
    changed = Image.new("RGB", (10, 10), "white")
    changed.putpixel((0, 0), (0, 0, 0))
    changed.save(right)
    assert changed_ratio(left, right) == pytest.approx(0.01)
