import json
from pathlib import Path

from scripts.route_complex_queries import classify_row, route_rows


def row(track: str, query: str, job_id: str = "complex-test") -> dict:
    return {"job_id": job_id, "technology_track": track, "query": query}


def test_threejs_always_uses_webgen() -> None:
    result = classify_row(row("threejs", "Build a small rotating product viewer."))
    assert result.route == "webgen"


def test_python_backend_stays_single_shot_because_webgen_is_npm_only() -> None:
    query = "Build a draggable real-time simulation with offline recovery and camera input."
    result = classify_row(row("python_backend", query))
    assert result.route == "single"


def test_vue_dashboard_without_four_complex_families_uses_single_shot() -> None:
    result = classify_row(row("vue", "Build a Vue dashboard with search, filters, and a detail panel."))
    assert result.route == "single"


def test_four_distinct_interaction_families_use_webgen() -> None:
    query = (
        "Build a draggable timeline with cross-view real-time synchronization, "
        "offline retry recovery, and a camera sensor workflow."
    )
    result = classify_row(row("vue", query))
    assert result.route == "webgen"
    assert len(result.complex_families) >= 4


def test_repeated_words_in_one_family_count_once() -> None:
    result = classify_row(row("react", "Support drag, draggable cards, a timeline, undo and redo."))
    assert result.route == "single"
    assert result.complex_families == ("direct_manipulation",)


def test_route_rows_emits_webgen_compatible_shape() -> None:
    rows = [
        row("typescript", "Build a typed form.", "complex-1"),
        row("webgl", "Build a shader demo.", "complex-2"),
    ]
    single, webgen = route_rows(rows)
    assert [item["job_id"] for item in single] == ["complex-1"]
    assert webgen[0]["id"] == "complex-2"
    assert webgen[0]["instruction"] == "Build a shader demo."
    assert webgen[0]["routing"]["route"] == "webgen"


def test_current_1k_routes_to_expected_stable_counts() -> None:
    source = Path("runs/artifactsbench_complex_stack_1k_qwen3.7max_20260731/queries.jsonl")
    rows = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
    single, webgen = route_rows(rows)
    assert len(single) == 885
    assert len(webgen) == 115
