from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import WebCoding_Data.construct.construct_text_editing as editing


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
    monkeypatch.setattr(
        editing,
        "existing_final_screenshots",
        lambda _: [{"path": "/tmp/final.png", "kind": "clean_final_render"}],
    )


def test_forward_strategy_extends_original_project(monkeypatch, tmp_path: Path) -> None:
    _setup(monkeypatch)

    class Synthesizer:
        def generate_forward_pair(self, generation_data, task_types):
            assert generation_data["dst_code"] == BASE_CODE
            assert task_types == ["Search", "Modal"]
            return {
                "task_type": task_types,
                "description": [{"task_type": "Search", "description": "Add search"}],
                "label_modified_files": [PATCH],
                "llm_raw_response": "",
            }

    project = tmp_path / "project"
    project.mkdir()
    result = editing._process_one(
        project, _args("forward"), Synthesizer(), ["Search", "Modal"]
    )

    assert result["status"] == "ok"
    assert result["construction_strategy"] == "forward"
    assert result["instruction"]["src_code"] == BASE_CODE
    assert result["reference"]["dst_code"][0]["code"] == (
        "<main>Existing<form>Search</form></main>"
    )
    assert result["images"]["src_screenshot"]
    assert result["images"]["dst_screenshot"] == []


def test_reverse_strategy_restores_removed_feature(monkeypatch, tmp_path: Path) -> None:
    _setup(monkeypatch)
    restore_patch = {
        "path": "index.html",
        "task_type": "Search",
        "search": "</main>",
        "replace": "<form>Search</form></main>",
    }
    complete_code = [
        {"path": "index.html", "code": "<main>Existing<form>Search</form></main>"}
    ]
    monkeypatch.setattr(
        editing,
        "build_generation_data",
        lambda _: {"dst_code": complete_code, "resources": []},
    )

    class Synthesizer:
        def generate_reverse_pair(self, generation_data, n_features):
            assert n_features == 2
            return {
                "task_type": ["Search"],
                "description": [{"task_type": "Search", "description": "Add search"}],
                "label_modified_files": [restore_patch],
                "llm_raw_response": "",
            }

    project = tmp_path / "project"
    project.mkdir()
    result = editing._process_one(
        project, _args("reverse"), Synthesizer(), ["Search", "Modal"]
    )

    assert result["status"] == "ok"
    assert result["instruction"]["src_code"] == BASE_CODE
    assert result["reference"]["dst_code"] == complete_code
    assert result["images"]["src_screenshot"] == []
    assert result["images"]["dst_screenshot"]
