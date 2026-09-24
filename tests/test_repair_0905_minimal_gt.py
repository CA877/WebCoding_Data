from reverse.edit.gt.repair_0905 import (
    focused_repair_context,
    fold_repairs,
    parse_repair,
)


def test_parse_and_fold_repair_into_original_patch():
    source = [{"path": "index.html", "code": "start\nend"}]
    original = [
        {
            "path": "index.html",
            "task_type": "Infinite Scroll",
            "search": "start",
            "replace": "start\nbroken observer",
        }
    ]
    raw = '{"patches":[{"path":"index.html","search":"broken observer","replace":"working observer"}]}'
    repairs = parse_repair(
        raw, {"Infinite Scroll": {"index.html"}}, ["Infinite Scroll"]
    )
    merged = fold_repairs(source, original, repairs)
    assert len(merged) == 1
    assert merged[0]["replace"] == "start\nworking observer"


def test_parse_grouped_repairs_requires_every_failed_task():
    raw = '{"patches":[' \
        '{"task_type":"Tree View","path":"page.html","search":"bad tree","replace":"tree"},' \
        '{"task_type":"Authentication","path":"index.html","search":"bad auth","replace":"auth"}' \
        ']}'
    repairs = parse_repair(
        raw,
        {"Tree View": {"page.html"}, "Authentication": {"index.html", "page.html"}},
        ["Tree View", "Authentication"],
    )
    assert [patch["task_type"] for patch in repairs] == ["Tree View", "Authentication"]


def test_focused_context_uses_inserted_code_and_unresolved_markers():
    current = [{"path": "index.html", "code": "head\n<!--EDIT:transition-->\nfixed script\ntail"}]
    original = [
        {"path": "index.html", "task_type": "Transition", "search": "old", "replace": "whole old target"},
        {"path": "index.html", "task_type": "Validation", "search": "marker", "replace": "fixed script"},
    ]
    context = focused_repair_context(current, original, ["Transition", "Validation"])
    assert context[0]["full_file"] is False
    assert "fixed script" in context[0]["excerpts"]
    assert any("<!--EDIT:transition-->" in value for value in context[0]["excerpts"])
