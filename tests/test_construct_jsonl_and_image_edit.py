import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from WebCoding_Data.construct.construct_common import append_jsonl, iter_jsonl_records
from WebCoding_Data.construct.construct_image_editing import _to_image_edit_record


def test_jsonl_reader_does_not_split_unicode_line_separator(tmp_path: Path) -> None:
    path = tmp_path / "records.jsonl"
    payload = {"instance_id": "one", "code": "before\u2028after"}
    append_jsonl(path, payload)

    assert list(iter_jsonl_records(path)) == [payload]


def test_forward_image_edit_keeps_clean_render_as_source(tmp_path: Path) -> None:
    screenshot = tmp_path / "project.png"
    screenshot.write_bytes(b"reviewed")
    record = {
        "instance_id": "project",
        "task": "text-editing",
        "status": "ok",
        "construction_strategy": "forward",
        "source_project": str(tmp_path),
        "images": {
            "src_screenshot": [{"path": str(screenshot), "kind": "clean_final_render"}],
            "dst_screenshot": [],
        },
    }

    converted = _to_image_edit_record(record)

    assert converted["task"] == "image-editing"
    assert converted["images"]["src_screenshot"][0]["path"] == str(screenshot)
    assert converted["images"]["dst_screenshot"] == []
    assert converted["metadata"]["base_task"] == "text-editing"
    assert converted["metadata"]["screenshot_state"] == "before_edit"


def test_reverse_image_edit_requires_a_rendered_source(tmp_path: Path) -> None:
    record = {
        "instance_id": "project",
        "task": "text-editing",
        "status": "ok",
        "construction_strategy": "reverse",
        "source_project": str(tmp_path),
        "images": {"src_screenshot": [], "dst_screenshot": []},
    }

    try:
        _to_image_edit_record(record)
    except ValueError as exc:
        assert "no reviewed source screenshot" in str(exc)
    else:
        raise AssertionError("reverse edit without a source render must be rejected")
