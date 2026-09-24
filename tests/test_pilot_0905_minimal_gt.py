import pytest

from reverse.edit.gt.pilot_0905 import (
    apply_exact,
    frozen_case,
    normalize_full_file_searches,
    parse_generation,
)


def case():
    descriptions = [
        {"task_type": "Dropdown", "description": "Add a filter."},
        {"task_type": "Carousel", "description": "Add a carousel."},
        {"task_type": "Tabs", "description": "Add tabs."},
        {"task_type": "Tooltip", "description": "Add tooltips."},
    ]
    return {
        "instance_id": "case",
        "task_type": ["Tabs", "Dropdown", "Tooltip", "Carousel"],
        "instruction": {
            "description": descriptions,
            "src_code": [{"path": "index.html", "code": "A B C D"}],
        },
    }


def test_frozen_case_uses_instruction_order():
    result = frozen_case(case())
    assert result["task_types"] == ["Dropdown", "Carousel", "Tabs", "Tooltip"]


def test_parse_and_apply_one_call_generation():
    frozen = frozen_case(case())
    checklist = [
        {"task_type": task_type, "files": ["index.html"], "implemented_behaviors": ["done"]}
        for task_type in frozen["task_types"]
    ]
    blocks = []
    for task_type, old, new in zip(frozen["task_types"], "ABCD", "abcd"):
        blocks.append(
            f'<search_replace path="index.html" task_type="{task_type}">'
            f"<search>{old}</search><replace>{new}</replace></search_replace>"
        )
    raw = (
        f"<description>{__import__('json').dumps(frozen['descriptions'])}</description>"
        f"<implementation_checklist>{__import__('json').dumps(checklist)}</implementation_checklist>"
        + "".join(blocks)
    )
    patches = parse_generation(raw, frozen)
    assert apply_exact(frozen["source_code"], patches)[0]["code"] == "a b c d"


def test_nested_patch_is_rejected():
    frozen = frozen_case(case())
    checklist = [
        {"task_type": task_type, "files": ["index.html"], "implemented_behaviors": ["done"]}
        for task_type in frozen["task_types"]
    ]
    raw = (
        f"<description>{__import__('json').dumps(frozen['descriptions'])}</description>"
        f"<implementation_checklist>{__import__('json').dumps(checklist)}</implementation_checklist>"
        '<search_replace path="index.html" task_type="Dropdown"><search>A</search>'
        '<replace>a</search></search_replace><search_replace path="index.html" '
        'task_type="Carousel"><search>B</search><replace>b</replace></search_replace>'
    )
    with pytest.raises(ValueError, match="nested patch"):
        parse_generation(raw, frozen)


def test_malformed_cdata_wrapper_is_normalized():
    frozen = frozen_case(case())
    checklist = [
        {"task_type": task_type, "files": ["index.html"], "implemented_behaviors": ["done"]}
        for task_type in frozen["task_types"]
    ]
    blocks = []
    for task_type, old, new in zip(frozen["task_types"], "ABCD", "abcd"):
        blocks.append(
            f'<search_replace path="index.html" task_type="{task_type}">'
            f"<search><![CDATA:{old}]]></search>"
            f"<replace><![CDATA:{new}]]></replace></search_replace>"
        )
    raw = (
        f"<description>{__import__('json').dumps(frozen['descriptions'])}</description>"
        f"<implementation_checklist>{__import__('json').dumps(checklist)}</implementation_checklist>"
        + "".join(blocks)
    )
    patches = parse_generation(raw, frozen)
    assert apply_exact(frozen["source_code"], patches)[0]["code"] == "a b c d"


def test_near_identical_full_file_search_is_normalized():
    source = [{"path": "index.html", "code": "header\n" + "content\n" * 100 + "footer"}]
    stale = "header\n" + "content\n" * 50 + "extra\n" + "content\n" * 50 + "footer"
    patches = [
        {"path": "index.html", "task_type": "Edit", "search": stale, "replace": "done"}
    ]
    normalized, events = normalize_full_file_searches(source, patches)
    assert len(events) == 1
    assert normalized[0]["search"] == source[0]["code"]
    assert apply_exact(source, normalized)[0]["code"] == "done"


def test_local_search_drift_is_not_normalized():
    source = [{"path": "index.html", "code": "header\nbody\nfooter"}]
    patches = [
        {"path": "index.html", "task_type": "Edit", "search": "bady", "replace": "done"}
    ]
    normalized, events = normalize_full_file_searches(source, patches)
    assert events == []
    assert normalized == patches
