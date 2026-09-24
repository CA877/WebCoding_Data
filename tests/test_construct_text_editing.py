from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reverse.edit.query.construct as editing


BASE_CODE = [{"path": "index.html", "code": "<main>Existing</main>"}]
PATCH = {
    "path": "index.html",
    "task_type": "Search",
    "search": "</main>",
    "replace": "<form>Search</form></main>",
}


def _args(strategy: str) -> SimpleNamespace:
    return SimpleNamespace(strategy=strategy, min_tasks=2, max_tasks=2, seed=0)


def _setup(monkeypatch) -> None:
    monkeypatch.setattr(
        editing,
        "build_generation_data",
        lambda _: {"dst_code": BASE_CODE, "resources": []},
    )


def test_edit_constructor_has_no_reverse_cli_option() -> None:
    source = Path(editing.__file__).read_text(encoding="utf-8")
    assert 'choices=("forward", "reverse")' not in source


def test_njulink_base_url_uses_openai_api_root() -> None:
    assert editing._normalize_api_base_url("https://api.nju-link.com") == (
        "https://api.nju-link.com/v1"
    )
    assert editing._normalize_api_base_url("https://example.com/v1") == (
        "https://example.com/v1"
    )


def test_edit_constructor_generates_instruction_without_answer(monkeypatch, tmp_path: Path) -> None:
    _setup(monkeypatch)

    class InstructionOnlySynthesizer:
        def generate_instruction(self, generation_data, task_types):
            assert generation_data["dst_code"] == BASE_CODE
            return {
                "task_type": task_types,
                "description": [
                    {"task_type": task_type, "description": f"Add {task_type}"}
                    for task_type in task_types
                ],
                "llm_raw_response": "<description>[]</description>",
                "llm_metadata": {"model": "test-model"},
                "llm_attempts": [],
            }

        def generate_forward_pair(self, *_args, **_kwargs):
            raise AssertionError("answer generation must not be called")

    result = editing._process_one(
        tmp_path / "project",
        _args("forward"),
        InstructionOnlySynthesizer(),
        ["Accordion", "Tabs", "Modal Dialog", "Dark Mode Toggle"],
        task_count=4,
    )

    assert result["status"] == "ok"
    assert result["construction_route"] == "edit_instruction_only"
    assert result["task_count"] == 4
    assert len(result["instruction"]) == 4
    assert result["instruction"] == result["description"]
    for answer_field in ("reference", "label_modified_files", "response", "images"):
        assert answer_field not in result


def test_edit_constructor_rejects_single_subtask(monkeypatch, tmp_path: Path) -> None:
    _setup(monkeypatch)
    result = editing._process_one(
        tmp_path / "project",
        _args("forward"),
        object(),
        ["Accordion"],
        task_count=1,
    )

    assert result["status"] == "error"
    assert "4 to 12 subtasks" in result["error"]
