import json
from types import SimpleNamespace

import reverse.generate.gt.generate as generate_module

from reverse.generate.gt.generate import (
    _generate_raw,
    generate_with_claim,
    load_rows,
    resolve_contract,
    source_id,
)
from reverse.generate.query.generate import page_scope


def test_current_generate_query_schema_is_consumed_directly(tmp_path):
    input_path = tmp_path / "queries.jsonl"
    usable = {
        "allocation_id": "Multi-page Product Website|WebGen|1",
        "product_category": "Multi-page Product Website",
        "benchmark": "WebGen",
        "query": "Build a multi-page product website with catalog and detail pages.",
        "status": "ok",
    }
    failed = {
        "allocation_id": "Tool / Productivity|ArtifactsBench|1",
        "product_category": "Tool / Productivity",
        "benchmark": "ArtifactsBench",
        "status": "failed",
        "error": "upstream timeout",
    }
    input_path.write_text(
        "\n".join(json.dumps(row) for row in (usable, failed)) + "\n",
        encoding="utf-8",
    )

    rows, unusable, duplicates, excluded = load_rows([input_path])

    assert rows == [usable]
    assert (unusable, duplicates, excluded) == (1, 0, 0)
    assert source_id(usable) == usable["allocation_id"]
    contract = resolve_contract(usable)
    assert contract.benchmark == "WebGen"
    assert contract.page_mode == "multi_page"


def test_responses_stream_accepts_complete_file_blocks_without_completed_event():
    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            return iter(
                [
                    SimpleNamespace(
                        type="response.output_text.delta",
                        delta="<<<FILE:index.html>>>\n<p>ok</p>\n<<<END_FILE>>>",
                    )
                ]
            )

        def get_final_response(self):
            raise RuntimeError("Didn't receive a `response.completed` event.")

    client = SimpleNamespace(
        responses=SimpleNamespace(stream=lambda **_request: Stream())
    )
    row = {
        "allocation_id": "Tool / Productivity|ArtifactsBench|1",
        "product_category": "Tool / Productivity",
        "benchmark": "ArtifactsBench",
        "query": "Build a timer.",
    }

    text, usage = _generate_raw(
        client,
        "gpt-5.5",
        row,
        resolve_contract(row),
        1000,
        False,
        True,
        "responses",
        "local-image-extension",
    )

    assert text.endswith("<<<END_FILE>>>")
    assert usage is None


def test_query_page_scope_is_explicit_and_matches_product_category():
    assert page_scope("Multi-page Product Website") == "multi_page"
    assert page_scope("React Full-stack Application") == "single_page"


def test_generate_with_claim_retries_then_succeeds(tmp_path, monkeypatch):
    attempts = []

    def fake_generate(*_args, **_kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            return {"instance_id": "case-1", "project_id": "case-1", "status": "error",
                    "error_type": "RuntimeError", "error": "stream closed", "duration_seconds": 1.0}
        return {"instance_id": "case-1", "project_id": "case-1", "status": "ok"}

    monkeypatch.setattr(generate_module, "generate_one", fake_generate)
    row = {"allocation_id": "case-1", "product_category": "Tool / Productivity",
           "benchmark": "ArtifactsBench", "query": "Build a timer."}
    result = generate_with_claim(
        object(), "gpt-5.5", row, tmp_path, 1000, False, True, "responses", "actor",
        "primary", 3, 0, 3600,
    )

    assert result["status"] == "ok"
    assert result["attempts"] == 2
    assert len(result["attempt_errors"]) == 1
    assert not list((tmp_path / "claims").glob("*.lock"))
