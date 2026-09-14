from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reverse.construct_text_editing as editing


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


def test_edit_constructor_has_no_reverse_cli_option() -> None:
    source = Path(editing.__file__).read_text(encoding="utf-8")
    assert 'choices=("forward", "reverse")' not in source
