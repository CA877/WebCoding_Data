from reverse.edit.gt.prepare_0905 import (
    clean_pending_record,
    descriptions,
)


def test_pending_record_removes_gt_and_preserves_instruction():
    row = {
        "instance_id": "case",
        "task_type": ["Dropdown"],
        "instruction": [{"task_type": "Dropdown", "description": "Add it."}],
        "response": [{"path": "a.js", "search": "a", "replace": "b"}],
        "patches": [{"path": "a.js", "search": "a", "replace": "b"}],
        "metadata": {
            "task_count": 1,
            "patch_count": 1,
            "patch_count_by_task": {"Dropdown": 1},
            "construction_model": "old-model",
        },
    }
    cleaned = clean_pending_record(row, ["Dropdown"])
    assert "response" not in cleaned
    assert "patches" not in cleaned
    assert cleaned["instruction"] == row["instruction"]
    assert cleaned["metadata"]["gt_status"] == "pending_regeneration"
    assert cleaned["metadata"]["source_gt_construction_model"] == "old-model"
    assert "patch_count" not in cleaned["metadata"]


def test_description_order_is_preserved_for_text_and_image():
    values = [
        {"task_type": "Tree View", "description": "Add tree."},
        {"task_type": "Dropdown", "description": "Add dropdown."},
    ]
    text = {"instruction": {"description": values}}
    image = {"instruction": values}
    assert descriptions(text, "text") == values
    assert descriptions(image, "image") == values
